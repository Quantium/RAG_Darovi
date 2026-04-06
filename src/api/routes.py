from __future__ import annotations

from typing import cast
from uuid import uuid4

import redis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    AutomationRequest,
    AutomationResponse,
    ChatRequest,
    ChatResponse,
    FileStatusItem,
    GenerateSQLRequest,
    GenerateSQLResponse,
    SourceReference,
    StatusResponse,
)
from src.api.app import verify_api_key
from src.automation.templates import parse_automation
from src.rag.chain import rag_answer, rag_answer_stream
from src.rag.retriever import RetrievedChunk

logger = structlog.get_logger()
router = APIRouter(dependencies=[Depends(verify_api_key)])


def _chunk_to_source(c: RetrievedChunk) -> SourceReference:
    return SourceReference(
        source_file_id=c.source_file_id,
        source_name=c.source_name,
        section_title=c.section_title,
        chunk_index=c.chunk_index,
        text_preview=c.text[:200],
        score=c.score,
    )


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


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    # Manual API Key verification for WebSockets as Depends() in router might not handle it easily via headers in some clients
    # For now, we assume verify_api_key in router handles it or we'd check here from query params.
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
            conversation_id = data.get("conversation_id") or str(uuid4())

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
                conversation_store.append(conversation_id, "user", query)
                conversation_store.append(conversation_id, "assistant", "".join(full_answer))

                serializable_sources = []
                for c in chunks:
                    source = _chunk_to_source(c)
                    serializable_sources.append(source.model_dump())

                await websocket.send_json(
                    {"type": "done", "sources": serializable_sources, "conversation_id": conversation_id}
                )

            except Exception as exc:
                logger.error("ws.query_error", error=str(exc))
                await websocket.send_json({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        logger.info("ws.disconnected")


@router.post("/generate-sql", response_model=GenerateSQLResponse)
async def generate_sql(request: Request, body: GenerateSQLRequest) -> GenerateSQLResponse:
    job_id = str(uuid4())
    settings = request.app.state.settings

    r = redis.Redis.from_url(settings.redis_cache_url)
    r.hset(f"sql_job:{job_id}", mapping={"status": "pending", "description": body.description})

    from src.worker.tasks import run_sql_generation

    run_sql_generation.delay(job_id, body.description, body.target_db)

    return GenerateSQLResponse(job_id=job_id, status="pending")


@router.get("/generate-sql/{job_id}", response_model=GenerateSQLResponse)
async def get_sql_job(request: Request, job_id: str) -> GenerateSQLResponse:
    r = redis.Redis.from_url(request.app.state.settings.redis_cache_url)
    job = cast(dict[bytes, bytes], r.hgetall(f"sql_job:{job_id}"))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return GenerateSQLResponse(
        job_id=job_id,
        status=job.get(b"status", b"unknown").decode(),
        schema_sql=job.get(b"schema_sql", b"").decode() or None if b"schema_sql" in job else None,
        insert_count=int(job.get(b"insert_count", b"0")),
        error=job.get(b"error", b"").decode() or None if b"error" in job else None,
    )


@router.post("/automations", response_model=AutomationResponse)
async def create_automation(body: AutomationRequest) -> AutomationResponse:
    try:
        config = parse_automation(body.yaml_config)
        # Store in an in-memory registry or DB. For now, just return success.
        return AutomationResponse(name=config.name, trigger=config.trigger, status="created")
    except (ValueError, Exception) as exc:
        return AutomationResponse(name="", trigger="", status="error", message=str(exc))


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    from src.metadata.repository import MetadataRepository

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)  # Assuming None lists all

    counts = {"pending": 0, "downloaded": 0, "converted": 0, "embedded": 0, "failed": 0, "skipped": 0}
    for f in files:
        if f.status in counts:
            counts[f.status] += 1
        else:
            counts["pending"] += 1  # Default

    return StatusResponse(
        total_files=len(files),
        pending=counts["pending"],
        downloaded=counts["downloaded"],
        converted=counts["converted"],
        embedded=counts["embedded"],
        failed=counts["failed"],
    )


@router.get("/status/files", response_model=list[FileStatusItem])
async def get_status_files(request: Request) -> list[FileStatusItem]:
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
