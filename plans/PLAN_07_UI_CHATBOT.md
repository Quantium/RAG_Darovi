# Phase 7: FastAPI + Chatbot UI with Document References

**Goal**: Implement the FastAPI application with all endpoints (REST + WebSocket), the CLI entry point, and a modern chatbot UI that displays LLM answers with clickable references to source documents.

**Depends on**: Phase 6 (retriever, LLM client, chain, generators, automations).

**Success Criteria**: Tests in `test_api/` turn GREEN. `uvicorn src.api.app:create_app --factory` starts. The chatbot UI renders at `http://localhost:8000`, accepts queries, shows streaming answers with source references. All `pytest` tests pass across the entire project.

---

## Step 7.1 — API Schemas

**File**: `src/api/schemas.py`

Pydantic request/response models:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    conversation_id: str | None = None
    document_type: str | None = None


class SourceReference(BaseModel):
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    text_preview: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    conversation_id: str


class GenerateSQLRequest(BaseModel):
    description: str = Field(..., min_length=1)
    target_db: str = "postgres"


class GenerateSQLResponse(BaseModel):
    job_id: str
    status: str  # pending | completed | failed
    schema_sql: str | None = None
    insert_count: int | None = None
    error: str | None = None


class AutomationRequest(BaseModel):
    yaml_config: str


class AutomationResponse(BaseModel):
    name: str
    trigger: str
    status: str  # created | error
    message: str | None = None


class StatusResponse(BaseModel):
    total_files: int
    pending: int
    downloaded: int
    converted: int
    embedded: int
    failed: int


class FileStatusItem(BaseModel):
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    error_message: str | None
    chunk_count: int
    last_processed_at: str | None
```

**Tests to turn GREEN**: `tests/test_api/test_schemas.py`

**SC**: `pytest tests/test_api/test_schemas.py -v` → all pass.

---

## Step 7.2 — FastAPI Application Factory

**File**: `src/api/app.py`

Full lifespan with real dependency construction, calling Phase 3's `configure_logging()` and `init_db()`, and Phase 5's `ensure_milvus_collection()`. Now includes API key authentication and conversation memory:

```python
from __future__ import annotations

from contextlib import asynccontextmanager

import redis
import structlog
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader

from config.settings import Settings
from src.logging import configure_logging
from src.metadata.repository import init_db
from src.rag.llm_client import create_llm_client
from src.rag.retriever import Retriever
from src.rag.conversation import ConversationStore
from src.vectorizer.embedder import BatchEmbedder
from src.vectorizer.milvus_store import MilvusStore
from src.generator.db_writer import DBWriter
from src.generator.sheets_writer import SheetsWriter
from src.worker.task_helpers import ensure_milvus_collection

logger = structlog.get_logger()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(request: Request, api_key: str | None = Depends(api_key_header)) -> None:
    """Middleware dependency: skip auth if API_KEY is not configured (dev mode)."""
    settings: Settings = request.app.state.settings
    configured_key = settings.api_key.get_secret_value()
    if not configured_key:
        return  # No key configured — auth disabled (dev mode)
    if api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = Settings()
    logger.info("app.startup", provider=settings.llm_provider)

    # Database
    await init_db(settings.database_url.get_secret_value())
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    engine = create_async_engine(settings.database_url.get_secret_value())

    # Milvus
    ensure_milvus_collection(settings)

    # Redis cache (DB 2 — isolated from broker/results)
    cache_client = redis.Redis.from_url(settings.redis_cache_url)

    # Conversation store (also on cache DB)
    conversation_store = ConversationStore(settings.redis_cache_url)

    # Services
    embedder = BatchEmbedder(settings)
    vector_store = MilvusStore(settings)
    retriever = Retriever(embedder=embedder, vector_store=vector_store, cache=cache_client)
    llm = create_llm_client(settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.retriever = retriever
    app.state.llm = llm
    app.state.embedder = embedder
    app.state.vector_store = vector_store
    app.state.conversation_store = conversation_store

    yield

    # Shutdown
    cache_client.close()
    await engine.dispose()
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    from src.api.routes import router

    app = FastAPI(
        title="RAG Darovi",
        version="1.0.0",
        lifespan=lifespan,
        dependencies=[Depends(verify_api_key)],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    # Static files mounted AFTER router — routes take priority, static is fallback
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
    return app
```

> **API Key Auth**: When `API_KEY` is set in `.env`, all API endpoints (REST and WebSocket) require the `X-API-Key` header. When `API_KEY` is empty (default), auth is disabled for local development. The static chatbot UI includes the key in its WebSocket connection and fetch calls (stored in `localStorage` via a settings modal).

> **Note**: `app.include_router(router)` is called before `app.mount("/", ...)`. FastAPI processes explicit routes first, so API endpoints like `/chat` and `/status` take priority. The `StaticFiles` mount at `/` with `html=True` serves the SPA for any unmatched path (e.g., `/` serves `index.html`).

---

## Step 7.3 — API Routes

**File**: `src/api/routes.py`

**Dependency injection**: Routes access services from `request.app.state`:

```python
from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    AutomationRequest, AutomationResponse,
    ChatRequest, ChatResponse,
    GenerateSQLRequest, GenerateSQLResponse,
    FileStatusItem, SourceReference, StatusResponse,
)
from src.rag.chain import rag_answer, rag_answer_stream
from src.rag.retriever import RetrievedChunk
from src.automation.templates import parse_automation

logger = structlog.get_logger()
router = APIRouter()


def _chunk_to_source(c: RetrievedChunk) -> SourceReference:
    return SourceReference(
        source_file_id=c.source_file_id,
        source_name=c.source_name,
        section_title=c.section_title,
        chunk_index=c.chunk_index,
        text_preview=c.text[:200],
        score=c.score,
    )
```

### `POST /chat`

Uses `rag_answer()` from Phase 6 — no logic duplication. Now passes conversation store for multi-turn context:

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    retriever = request.app.state.retriever
    llm = request.app.state.llm
    conversation_store = request.app.state.conversation_store
    conversation_id = body.conversation_id or str(uuid4())

    answer, chunks = await rag_answer(
        query=body.query,
        retriever=retriever,
        llm=llm,
        document_type=body.document_type,
        conversation_store=conversation_store,
        conversation_id=conversation_id,
    )
    sources = [_chunk_to_source(c) for c in chunks]

    logger.info("api.chat", conversation_id=conversation_id, sources=len(sources))
    return ChatResponse(answer=answer, sources=sources, conversation_id=conversation_id)
```

### `WS /ws/chat`

Uses `rag_answer_stream()` from Phase 6. Includes error handling:

```python
@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    retriever = websocket.app.state.retriever
    llm = websocket.app.state.llm
    conversation_store = websocket.app.state.conversation_store

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "query":
                continue

            query = data.get("query", "")
            document_type = data.get("document_type")
            conversation_id = data.get("conversation_id")

            try:
                token_stream, chunks = await rag_answer_stream(
                    query=query,
                    retriever=retriever,
                    llm=llm,
                    document_type=document_type,
                    conversation_store=conversation_store,
                    conversation_id=conversation_id,
                )
                full_answer = []
                async for token in token_stream:
                    full_answer.append(token)
                    await websocket.send_json({"type": "token", "content": token})

                # Persist conversation after stream completes
                if conversation_id:
                    conversation_store.append(conversation_id, "user", query)
                    conversation_store.append(conversation_id, "assistant", "".join(full_answer))

                sources = [_chunk_to_source(c).model_dump() for c in chunks]
                await websocket.send_json({"type": "done", "sources": sources})

            except Exception as exc:
                logger.error("ws.query_error", error=str(exc))
                await websocket.send_json({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        logger.info("ws.disconnected")
```

**Message protocol**:
```json
// Incoming
{"type": "query", "query": "...", "document_type": "pdf", "conversation_id": "uuid"}

// Outgoing (streaming)
{"type": "token", "content": "The quarterly..."}
{"type": "token", "content": " revenue was..."}
{"type": "done", "sources": [...]}

// Outgoing (error)
{"type": "error", "message": "Connection refused"}
```

### `POST /generate-sql`

Dispatches SQL generation as a **Celery task** for long-running operations. Job ID stored in Redis:

```python
@router.post("/generate-sql", response_model=GenerateSQLResponse)
async def generate_sql(request: Request, body: GenerateSQLRequest) -> GenerateSQLResponse:
    import redis
    job_id = str(uuid4())
    settings = request.app.state.settings

    r = redis.Redis.from_url(settings.redis_cache_url)
    r.hset(f"sql_job:{job_id}", mapping={"status": "pending", "description": body.description})

    from src.worker.tasks import run_sql_generation
    run_sql_generation.delay(job_id, body.description, body.target_db)

    return GenerateSQLResponse(job_id=job_id, status="pending")
```

> **Note**: `run_sql_generation` is a new Celery task added to `src/worker/tasks.py` in this phase. It calls `SQLGenerator.discover_schema()` + `extract_data()` + `DBWriter.execute_many()` and updates the Redis hash with results.

### `GET /generate-sql/{job_id}`

```python
@router.get("/generate-sql/{job_id}", response_model=GenerateSQLResponse)
async def get_sql_job(request: Request, job_id: str) -> GenerateSQLResponse:
    import redis
    r = redis.Redis.from_url(request.app.state.settings.redis_cache_url)
    job = r.hgetall(f"sql_job:{job_id}")
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")

    return GenerateSQLResponse(
        job_id=job_id,
        status=job.get(b"status", b"unknown").decode(),
        schema_sql=job.get(b"schema_sql", b"").decode() or None,
        insert_count=int(job.get(b"insert_count", b"0")),
        error=job.get(b"error", b"").decode() or None,
    )
```

### `POST /automations`

```python
@router.post("/automations", response_model=AutomationResponse)
async def create_automation(body: AutomationRequest) -> AutomationResponse:
    try:
        config = parse_automation(body.yaml_config)
        # Store in an in-memory registry (upgrade to DB in future)
        return AutomationResponse(name=config.name, trigger=config.trigger, status="created")
    except (ValueError, Exception) as exc:
        return AutomationResponse(name="", trigger="", status="error", message=str(exc))
```

### `GET /automations`

```python
@router.get("/automations")
async def list_automations() -> list[dict]:
    # Return from in-memory registry or DB
    return []
```

### `GET /status`

```python
@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.metadata.repository import MetadataRepository

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)  # all files

    counts = {"pending": 0, "downloaded": 0, "converted": 0, "embedded": 0, "failed": 0}
    for f in files:
        if f.status in counts:
            counts[f.status] += 1

    return StatusResponse(total_files=len(files), **counts)
```

### `GET /status/files`

```python
@router.get("/status/files", response_model=list[FileStatusItem])
async def get_status_files(request: Request) -> list[FileStatusItem]:
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.metadata.repository import MetadataRepository

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)

    return [
        FileStatusItem(
            drive_file_id=f.drive_file_id,
            name=f.name,
            mime_type=f.mime_type,
            status=f.status,
            error_message=f.error_message,
            chunk_count=f.chunk_count,
            last_processed_at=str(f.last_processed_at) if f.last_processed_at else None,
        )
        for f in files
    ]
```

**Tests to turn GREEN**: `tests/test_api/test_routes.py`

**SC**: `pytest tests/test_api/test_routes.py -v` → all pass.

---

## Step 7.4 — CLI Entry Point

**File**: `src/main.py`

Uses `argparse` for CLI parsing. Each command delegates to the appropriate module:

```python
from __future__ import annotations

import argparse
import asyncio
import sys

from config.settings import Settings
from src.logging import configure_logging


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="RAG Darovi Pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Start FastAPI server")
    sub.add_parser("worker", help="Start Celery worker")
    sub.add_parser("beat", help="Start Celery Beat scheduler")
    sub.add_parser("ingest", help="Run one-time full ingestion from Drive")

    query_p = sub.add_parser("query", help="Query documents from CLI")
    query_p.add_argument("text", help="The question to ask")
    query_p.add_argument("--type", dest="doc_type", help="Filter by doc type (doc/sheet/pdf)")

    args = parser.parse_args()
    settings = Settings()

    if args.command == "serve":
        import uvicorn
        uvicorn.run(
            "src.api.app:create_app",
            factory=True,
            host=settings.api_host,
            port=settings.api_port,
        )

    elif args.command == "worker":
        from src.worker.celery_app import app
        app.worker_main(["worker", "--loglevel=info", "-Q", "download,convert,embed"])

    elif args.command == "beat":
        from src.worker.celery_app import app
        app.worker_main(["beat", "--loglevel=info"])

    elif args.command == "ingest":
        from src.worker.tasks import run_incremental_sync
        run_incremental_sync.delay()
        print("Ingestion dispatched. Monitor via `GET /status`.")

    elif args.command == "query":
        asyncio.run(_cli_query(settings, args.text, args.doc_type))


async def _cli_query(settings: Settings, query: str, doc_type: str | None) -> None:
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore
    from src.rag.retriever import Retriever
    from src.rag.llm_client import create_llm_client
    from src.rag.chain import rag_answer

    embedder = BatchEmbedder(settings)
    store = MilvusStore(settings)
    retriever = Retriever(embedder=embedder, vector_store=store)
    llm = create_llm_client(settings)

    answer, sources = await rag_answer(query, retriever, llm, document_type=doc_type)
    print(f"\n{answer}\n")
    if sources:
        print("Sources:")
        for s in sources:
            print(f"  [{s.source_name}] {s.section_title} (score: {s.score:.2f})")


if __name__ == "__main__":
    main()
```

Commands:

```bash
python -m src.main serve           # Start FastAPI server
python -m src.main worker          # Start Celery worker
python -m src.main beat            # Start Celery Beat
python -m src.main ingest          # Dispatch one-time ingestion
python -m src.main query "..."     # CLI query (prints answer + sources)
python -m src.main query "..." --type pdf  # Filter by document type
```

---

## Step 7.5 — Chatbot UI

**Directory**: `static/`

A single-page application served by FastAPI's `StaticFiles`:

```
static/
├── index.html
├── styles.css
└── app.js
```

### Design Requirements

**Layout**:
- Clean, minimal interface with a centered chat container (max-width 800px).
- Dark/light mode toggle.
- Header with app title and pipeline status indicator.
- Chat message area (scrollable) with user/assistant message bubbles.
- Input bar at the bottom with text input + send button.
- Optional sidebar with document type filter (All / Docs / Sheets / PDFs).

**Message Rendering**:
- User messages: right-aligned, accent-colored bubble.
- Assistant messages: left-aligned, neutral bubble with markdown rendering.
- **Source references** displayed below each assistant message as collapsible cards:

```
📄 quarterly-report-q3.pdf | Section: Revenue | Relevance: 95%
  "Total revenue reached $1.2M, a 15% increase over Q2..."
```

- Each reference card shows:
  - File icon based on type (📄 PDF, 📝 Doc, 📊 Sheet)
  - File name
  - Section title
  - Relevance score (percentage)
  - Text preview (first ~200 chars, expandable on click)

**Streaming**:
- Connect via WebSocket to `/ws/chat`.
- Display tokens as they arrive (typing effect).
- Show a loading indicator while waiting for first token.
- Render sources after the `done` message.
- On `error` message, display error in the assistant bubble.

**Conversation History**:
- Maintain conversation in local state (JavaScript array).
- `conversation_id` generated as UUID on first message, reused for multi-turn.
- Clear chat button resets conversation and generates a new UUID.

### index.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAG Darovi</title>
    <link rel="stylesheet" href="/styles.css">
</head>
<body>
    <div id="app">
        <header>
            <h1>RAG Darovi</h1>
            <div id="status-indicator" title="Pipeline status"></div>
            <button id="clear-chat" aria-label="Clear chat" title="New conversation">🗑️</button>
            <button id="theme-toggle" aria-label="Toggle theme">🌙</button>
        </header>

        <aside id="filters">
            <button class="filter-btn active" data-type="">All</button>
            <button class="filter-btn" data-type="doc">📝 Docs</button>
            <button class="filter-btn" data-type="sheet">📊 Sheets</button>
            <button class="filter-btn" data-type="pdf">📄 PDFs</button>
        </aside>

        <main id="chat-container">
            <div id="messages"></div>
        </main>

        <footer>
            <form id="chat-form">
                <input type="text" id="query-input"
                       placeholder="Ask about your documents..."
                       autocomplete="off" required>
                <button type="submit" id="send-btn">Send</button>
            </form>
        </footer>
    </div>
    <script src="/app.js"></script>
</body>
</html>
```

### styles.css

Key design tokens and behavior:
- CSS custom properties for theming (`--bg`, `--text`, `--accent`, `--bubble-user`, `--bubble-assistant`).
- Light mode: `#ffffff` bg, `#1a1a2e` text, `#3b82f6` accent.
- Dark mode: `#1a1a2e` bg, `#e2e8f0` text, `#06b6d4` accent.
- Smooth transitions on theme toggle (`transition: background-color 0.3s, color 0.3s`).
- Source reference cards: bordered, slightly indented, with hover effect (`transform: translateY(-1px)`).
- Responsive: on mobile (≤ 640px), chat fills viewport, filters become horizontal scrollable row.
- Loading indicator: animated dots (`...`) inside an assistant bubble.
- Input bar sticky at bottom with `position: sticky`.

### app.js

Core logic:

```javascript
// Pseudocode — implement as vanilla JS (no framework)
const state = {
    ws: null,
    conversationId: crypto.randomUUID(),
    documentType: "",
    messages: [],
    apiKey: localStorage.getItem("rag_api_key") || "",
};

function connectWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    state.ws = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    state.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "token") appendToken(msg.content);
        else if (msg.type === "done") renderSources(msg.sources);
        else if (msg.type === "error") renderError(msg.message);
    };

    state.ws.onclose = () => setTimeout(connectWebSocket, 3000); // auto-reconnect
}

function sendQuery(query) {
    addUserMessage(query);
    createAssistantBubble(); // empty, will fill with tokens
    state.ws.send(JSON.stringify({
        type: "query",
        query: query,
        document_type: state.documentType || undefined,
        conversation_id: state.conversationId,
    }));
}

// Status polling (include API key header)
setInterval(async () => {
    const headers = state.apiKey ? { "X-API-Key": state.apiKey } : {};
    const res = await fetch("/status", { headers });
    const data = await res.json();
    updateStatusIndicator(data);
}, 30000);
```

Key behaviors:
1. WebSocket connection management (auto-reconnect on close with 3s delay).
2. Send query with selected document type filter.
3. Render streaming tokens into the current assistant bubble.
4. On `done` message, render source reference cards below the answer.
5. On `error` message, show error text in the assistant bubble.
6. Basic markdown rendering: bold (`**text**`), code blocks, headers (manual parsing or lightweight CDN lib like `marked`).
7. Theme toggle persisted in `localStorage`.
8. Status indicator polls `GET /status` every 30s, shows colored dot (green/yellow/red based on failed count).
9. Clear chat button resets `state.messages` and generates new `conversationId`.
10. Disable send button while streaming (re-enable after `done`/`error`).

---

## Step 7.6 — Integration Verification

### Implementation order within this phase

Steps 7.1 (schemas), 7.4 (CLI), and 7.5 (UI) are independent and **can be implemented in parallel**. Steps 7.2 (app factory) and 7.3 (routes) are sequential. Step 7.6 runs after everything.

```
7.1 (Schemas) ─────→ 7.2 (App Factory) → 7.3 (Routes)
7.4 (CLI) ──────────────────────────────────────────────→ 7.6 (Integration)
7.5 (UI: HTML/CSS/JS) ─────────────────────────────────→ 7.6 (Integration)
```

### Run full test suite

```bash
pytest -v --tb=short
```

**All tests across all phases must be GREEN.**

### End-to-End Manual Verification

1. Start infrastructure:
   ```bash
   docker compose up -d
   ```

2. Pull models:
   ```bash
   docker compose exec ollama ollama pull nomic-embed-text
   docker compose exec ollama ollama pull llama3
   ```

3. Start the API:
   ```bash
   python -m src.main serve
   ```

4. Open `http://localhost:8000` in a browser.

5. Verify:
   - [ ] Chat interface loads with header, input bar, and filter buttons.
   - [ ] Status indicator shows pipeline stats (polls every 30s).
   - [ ] Typing a query and pressing Send triggers WebSocket connection.
   - [ ] Tokens stream in real-time into the assistant bubble.
   - [ ] Source references appear below the answer with file name, section, and preview.
   - [ ] Clicking a source reference expands the full chunk text.
   - [ ] Document type filter narrows search results.
   - [ ] Dark/light mode toggle works and persists across page reloads.
   - [ ] Clear chat button resets conversation.
   - [ ] `GET /status` returns correct counts.
   - [ ] `GET /status/files` lists all processed files.
   - [ ] `POST /generate-sql` returns a job ID and polling returns results.
   - [ ] CLI `python -m src.main query "What is revenue?"` prints answer + sources.

---

## Output of This Phase

- `src/api/schemas.py` — Pydantic request/response models (including `AutomationResponse`)
- `src/api/app.py` — FastAPI factory with full lifespan (`configure_logging`, `init_db`, `ensure_milvus_collection`, Redis cache client, `ConversationStore`, shutdown cleanup) + **API key auth middleware** (disabled when `API_KEY` is empty)
- `src/api/routes.py` — `router = APIRouter()` with all REST + WebSocket endpoints using `rag_answer` / `rag_answer_stream` from Phase 6, with **conversation memory** via `ConversationStore`
- `src/main.py` — CLI entry point (`serve`, `worker`, `beat`, `ingest`, `query`) with `argparse`
- `static/index.html` — Chatbot UI markup with clear chat button
- `static/styles.css` — Modern responsive styling with dark/light theme via CSS custom properties
- `static/app.js` — WebSocket client with auto-reconnect, streaming, source rendering, error handling, status polling, **API key support**, **conversation_id in messages**
- All `test_api/` tests GREEN
- **Full project test suite GREEN** (`pytest -v` → 100% pass)
