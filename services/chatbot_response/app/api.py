from __future__ import annotations

from functools import partial
from pathlib import Path
from uuid import uuid4

import psycopg2
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .auth import (
    create_session,
    delete_session,
    get_session_username,
    require_session,
    verify_user,
)
from .conversation import ConversationStore
from .llm import LLMService
from .retrieval_client import RetrievalClient
from .schemas import ChatRequest, ChatResponse, LoginRequest, LoginResponse, LogoutRequest, RateRequest
from .settings import Settings


def _pg_url(db_url: str) -> str:
    """Convert a SQLAlchemy-style PostgreSQL URL to a plain psycopg2-compatible URL.

    Args:
        db_url: SQLAlchemy connection string (may include driver prefix).

    Returns:
        URL with the 'postgresql+psycopg2://' prefix replaced by 'postgresql://'.
    """
    return db_url.replace("postgresql+psycopg2://", "postgresql://")


def _save_interaction_sync(db_url: str, conversation_id: str, question: str, answer: str, username: str) -> int:
    """Persist a chat interaction to the database and return its generated row ID.

    Args:
        db_url: SQLAlchemy-style database connection URL.
        conversation_id: UUID identifying the ongoing conversation.
        question: The user's query text.
        answer: The assistant's response text.
        username: The authenticated username of the asker.

    Returns:
        The auto-generated primary key of the inserted chat_interactions row.
    """
    conn = psycopg2.connect(_pg_url(db_url))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_interactions (conversation_id, question, answer, username)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (conversation_id, question, answer, username),
            )
            row_id: int = cur.fetchone()[0]
        conn.commit()
        return row_id
    finally:
        conn.close()


def _update_rating_sync(db_url: str, interaction_id: int, rating: str, correction: str | None) -> None:
    """Update the rating and optional correction for an existing chat interaction.

    Args:
        db_url: SQLAlchemy-style database connection URL.
        interaction_id: Primary key of the chat_interactions row to update.
        rating: User-provided rating value (e.g. 'good', 'bad').
        correction: Optional corrected answer text provided by the user.
    """
    conn = psycopg2.connect(_pg_url(db_url))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE chat_interactions SET rating = %s, correction = %s WHERE id = %s",
                (rating, correction, interaction_id),
            )
        conn.commit()
    finally:
        conn.close()

_AGGREGATE_KEYWORDS = (
    "cuántos", "cuantos", "cuántas", "cuantas", "cuál es el total", "total de",
    "lista", "listado", "enumera", "enumerar", "todos los", "todas las",
    "hay en total", "existen", "medicamentos hay", "productos hay",
    "registros hay", "registros sanitarios hay",
)


def _aggregate_top_k(query: str, settings: Settings) -> int:
    """Return the appropriate retrieval top-k based on whether the query is aggregate.

    Aggregate queries (counts, listings) use a higher top-k to capture more results.

    Args:
        query: The user's natural-language query.
        settings: Application settings carrying the configured top-k values.

    Returns:
        Top-k integer to pass to the retrieval service.
    """
    q = query.lower()
    if any(kw in q for kw in _AGGREGATE_KEYWORDS):
        return settings.retrieval_top_k_aggregate
    return settings.retrieval_top_k_default


async def verify_api_key(request: Request) -> None:
    """FastAPI dependency that raises HTTP 401 when the X-API-Key header is invalid.

    A missing or blank configured key disables the check entirely.

    Args:
        request: Incoming FastAPI request carrying the header and app state.

    Raises:
        HTTPException: 401 if a key is configured and the incoming header does not match.
    """
    settings: Settings = request.app.state.settings
    configured = settings.api_key.get_secret_value()
    if not configured:
        return
    incoming = request.headers.get("X-API-Key") or ""
    if incoming != configured:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application with all routes and middleware.

    Returns:
        Fully configured FastAPI instance ready to serve requests.
    """
    app = FastAPI(title="Chatbot Response Service", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    settings = Settings()
    redis_client = redis.Redis.from_url(settings.redis_cache_url)
    app.state.settings = settings
    app.state.redis_client = redis_client
    app.state.retrieval = RetrievalClient(settings)
    app.state.llm = LLMService(settings)
    app.state.conversation = ConversationStore(redis_client, ttl_seconds=settings.conversation_ttl_seconds)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Return a simple liveness check payload."""
        return {"status": "ok"}

    @app.post("/auth/login", response_model=LoginResponse)
    async def login(body: LoginRequest) -> LoginResponse:
        """Authenticate a user and return a session token stored in Redis.

        Args:
            body: Login credentials containing username and password.

        Returns:
            LoginResponse with the session token and username.

        Raises:
            HTTPException: 401 if credentials are invalid.
        """
        db_url = settings.database_url_sync.get_secret_value()
        ok = await verify_user(db_url, body.username, body.password)
        if not ok:
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
        token = create_session(redis_client, body.username)
        return LoginResponse(token=token, username=body.username)

    @app.post("/auth/logout")
    async def logout(body: LogoutRequest) -> dict[str, str]:
        """Invalidate the session token and remove it from Redis.

        Args:
            body: Logout request containing the session token to revoke.

        Returns:
            Status dict confirming the logout.
        """
        delete_session(redis_client, body.token)
        return {"status": "ok"}

    @app.post(
        "/chat",
        response_model=ChatResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def chat(body: ChatRequest, request: Request, username: str = Depends(require_session)) -> ChatResponse:
        """Handle a single-turn chat request: retrieve context, call LLM, persist interaction.

        Args:
            body: Chat request containing the query, optional conversation ID, and document type filter.
            request: Incoming FastAPI request carrying app state and headers.

        Returns:
            ChatResponse with the answer, source references, conversation ID, and interaction ID.
        """
        import asyncio
        retrieval: RetrievalClient = app.state.retrieval
        llm: LLMService = app.state.llm
        conversation: ConversationStore = app.state.conversation
        conv_id = body.conversation_id or str(uuid4())
        api_key = request.headers.get("X-API-Key")
        top_k = _aggregate_top_k(body.query, settings)
        retrieve = await retrieval.retrieve(query=body.query, top_k=top_k, document_type=body.document_type, api_key=api_key)
        history = conversation.get_history(conv_id)
        answer = await llm.answer(query=body.query, context=retrieve.context, history=history)
        conversation.append(conv_id, "user", body.query)
        conversation.append(conv_id, "assistant", answer)
        db_url = settings.database_url_sync.get_secret_value()
        loop = asyncio.get_event_loop()
        interaction_id = await loop.run_in_executor(
            None, partial(_save_interaction_sync, db_url, conv_id, body.query, answer, username)
        )
        return ChatResponse(answer=answer, sources=retrieve.sources, conversation_id=conv_id, interaction_id=interaction_id)

    @app.post("/rate", dependencies=[Depends(require_session)])
    async def rate(body: RateRequest) -> dict[str, str]:
        """Record the user's rating (and optional correction) for a previous interaction.

        Args:
            body: Rating payload with interaction ID, rating value, and optional correction.

        Returns:
            Status dict confirming the update.
        """
        import asyncio
        db_url = settings.database_url_sync.get_secret_value()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, partial(_update_rating_sync, db_url, body.interaction_id, body.rating, body.correction)
        )
        return {"status": "ok"}

    @app.websocket("/ws/chat")
    async def ws_chat(ws: WebSocket) -> None:
        """Handle a streaming WebSocket chat session, sending tokens as they are generated.

        Validates API key and session token before accepting the connection.
        Each message with type 'query' triggers retrieval, LLM generation, and token streaming.

        Args:
            ws: The WebSocket connection instance.
        """
        settings_ws: Settings = app.state.settings
        configured = settings_ws.api_key.get_secret_value()
        incoming_key = ws.query_params.get("api_key") or ws.headers.get("x-api-key") or ws.headers.get("X-API-Key") or ""
        if configured and incoming_key != configured:
            await ws.close(code=1008)
            return
        token = ws.query_params.get("token")
        ws_username = get_session_username(redis_client, token) if token else None
        if not ws_username:
            await ws.close(code=1008)
            return
        await ws.accept()
        retrieval: RetrievalClient = app.state.retrieval
        llm: LLMService = app.state.llm
        conversation: ConversationStore = app.state.conversation
        try:
            while True:
                payload = await ws.receive_json()
                if payload.get("type") != "query":
                    continue
                query = payload.get("query", "").strip()
                if not query:
                    continue
                doc_type = payload.get("document_type")
                conv_id = payload.get("conversation_id") or str(uuid4())
                top_k = _aggregate_top_k(query, settings_ws)
                retrieve = await retrieval.retrieve(query=query, top_k=top_k, document_type=doc_type, api_key=incoming_key or None)
                history = conversation.get_history(conv_id)
                answer = await llm.answer(query=query, context=retrieve.context, history=history)
                for token_word in answer.split():
                    await ws.send_json({"type": "token", "content": token_word + " "})
                conversation.append(conv_id, "user", query)
                conversation.append(conv_id, "assistant", answer)
                import asyncio as _aio
                db_url_ws = settings_ws.database_url_sync.get_secret_value()
                ws_loop = _aio.get_event_loop()
                interaction_id = await ws_loop.run_in_executor(
                    None, partial(_save_interaction_sync, db_url_ws, conv_id, query, answer, ws_username)
                )
                await ws.send_json(
                    {
                        "type": "done",
                        "conversation_id": conv_id,
                        "interaction_id": interaction_id,
                        "sources": [item.model_dump() for item in retrieve.sources],
                    }
                )
        except WebSocketDisconnect:
            return

    static_root = Path(__file__).resolve().parent.parent / "static"

    @app.get("/")
    async def index() -> FileResponse:
        """Serve the chat UI HTML entry point."""
        return FileResponse(static_root / "index.html")

    @app.get("/app.js")
    async def js() -> FileResponse:
        """Serve the chat UI JavaScript bundle."""
        return FileResponse(static_root / "app.js", media_type="application/javascript")

    @app.get("/styles.css")
    async def css() -> FileResponse:
        """Serve the chat UI stylesheet."""
        return FileResponse(static_root / "styles.css", media_type="text/css")

    return app
