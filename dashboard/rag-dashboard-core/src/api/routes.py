from __future__ import annotations

from typing import cast
from uuid import uuid4

import redis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    AutomationRequest,
    AutomationResponse,
    ChatRequest,
    ChatResponse,
    FileStatusItem,
    GenerateSQLRequest,
    GenerateSQLResponse,
    IngestResponse,
    RawDataItem,
    SourceReference,
    StatusResponse,
)
from src.api.app import verify_api_key
from src.automation.templates import parse_automation
from src.rag.chain import rag_answer, rag_answer_stream
from src.rag.retriever import RetrievedChunk
from src.storage.backend import MinIOStorage

logger = structlog.get_logger()
router = APIRouter()


def _verify_api_key_for_file_open(request: Request) -> None:
    """Raise HTTP 401 if the X-API-Key header or 'api_key' query param is invalid.

    Accepts the key via header (X-API-Key / x-api-key) or query string (api_key).

    Args:
        request: Incoming FastAPI request carrying headers and query params.

    Raises:
        HTTPException: 401 if a key is configured and none of the provided values match.
    """
    configured_key = request.app.state.settings.api_key.get_secret_value()
    if not configured_key:
        return
    header_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    query_key = request.query_params.get("api_key")
    provided_key = header_key or query_key or ""
    if provided_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _chunk_to_source(c: RetrievedChunk) -> SourceReference:
    """Convert a RetrievedChunk to a SourceReference API response model.

    Args:
        c: Retrieved chunk from Milvus search.

    Returns:
        SourceReference with the chunk's metadata and a truncated text preview.
    """
    return SourceReference(
        source_file_id=c.source_file_id,
        source_name=c.source_name,
        section_title=c.section_title,
        chunk_index=c.chunk_index,
        text_preview=c.text[:200],
        score=c.score,
    )


def _safe_decode_extracted_text(raw_bytes: bytes, max_chars: int = 6000) -> str:
    """Decode bytes to UTF-8 and truncate to a safe maximum character count.

    Args:
        raw_bytes: Raw bytes from a MinIO object read.
        max_chars: Maximum characters to return before appending an ellipsis.

    Returns:
        Decoded and optionally truncated text string.
    """
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…"


def _raw_text_availability(
    storage: MinIOStorage, bucket_name: str, minio_text_key: str | None
) -> tuple[bool, str | None]:
    """Check whether a text object exists in MinIO and return availability with a reason.

    Args:
        storage: MinIO storage backend instance.
        bucket_name: Name of the MinIO bucket to check.
        minio_text_key: Object key to verify, or None if not yet recorded.

    Returns:
        Tuple of (available, reason). If available is True, reason is None.
        If False, reason is a human-readable explanation.
    """
    if not minio_text_key:
        return False, "No extracted text key recorded."
    try:
        if storage.exists(bucket_name, minio_text_key):
            return True, None
        return False, "Extracted text object not found in storage."
    except Exception:
        return False, "Could not verify extracted text in storage."


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Handle a single-turn RAG chat request: retrieve, answer, and return sources.

    Args:
        request: Incoming FastAPI request carrying app state.
        body: Chat request with query, optional conversation ID, and document type filter.

    Returns:
        ChatResponse with the answer, source references, and conversation ID.
    """
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
    """Handle a streaming WebSocket RAG chat session, yielding answer tokens in real time.

    Validates the API key before accepting the connection. Each message with type 'query'
    triggers retrieval, streamed LLM generation, and a final 'done' frame with sources.

    Args:
        websocket: The WebSocket connection instance.
    """
    settings_ws = websocket.app.state.settings
    configured_key = settings_ws.api_key.get_secret_value()
    if configured_key:
        q_key = websocket.query_params.get("api_key")
        header_key = websocket.headers.get("x-api-key") or websocket.headers.get("X-API-Key")
        if (q_key or header_key or "") != configured_key:
            await websocket.close(code=1008)
            return

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


@router.post("/generate-sql", response_model=GenerateSQLResponse, dependencies=[Depends(verify_api_key)])
async def generate_sql(request: Request, body: GenerateSQLRequest) -> GenerateSQLResponse:
    """Queue a Celery SQL generation job and return the assigned job ID immediately.

    Args:
        request: Incoming FastAPI request carrying app state.
        body: SQL generation request with description and target database.

    Returns:
        GenerateSQLResponse with the job ID and initial 'pending' status.
    """
    job_id = str(uuid4())
    settings = request.app.state.settings

    r = redis.Redis.from_url(settings.redis_cache_url)
    r.hset(f"sql_job:{job_id}", mapping={"status": "pending", "description": body.description})

    from src.worker.tasks import run_sql_generation

    run_sql_generation.delay(job_id, body.description, body.target_db)

    return GenerateSQLResponse(job_id=job_id, status="pending")


@router.get("/generate-sql/{job_id}", response_model=GenerateSQLResponse, dependencies=[Depends(verify_api_key)])
async def get_sql_job(request: Request, job_id: str) -> GenerateSQLResponse:
    """Poll the status and result of a previously queued SQL generation job.

    Args:
        request: Incoming FastAPI request carrying app state.
        job_id: UUID of the SQL generation job to check.

    Returns:
        GenerateSQLResponse with the current status and result if complete.

    Raises:
        HTTPException: 404 if the job ID is not found in Redis.
    """
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


@router.post("/automations", response_model=AutomationResponse, dependencies=[Depends(verify_api_key)])
async def create_automation(body: AutomationRequest) -> AutomationResponse:
    """Parse and register an automation from a YAML configuration string.

    Args:
        body: Automation request containing the raw YAML config.

    Returns:
        AutomationResponse with the name, trigger, and creation status.
    """
    try:
        config = parse_automation(body.yaml_config)
        # Store in an in-memory registry or DB. For now, just return success.
        return AutomationResponse(name=config.name, trigger=config.trigger, status="created")
    except (ValueError, Exception) as exc:
        return AutomationResponse(name="", trigger="", status="error", message=str(exc))


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(verify_api_key)])
async def ingest_documents() -> IngestResponse:
    """Queue a Celery incremental sync task and return immediately.

    Returns:
        IngestResponse confirming the job was queued.
    """
    from src.worker.tasks import run_incremental_sync

    run_incremental_sync.delay()
    return IngestResponse(status="queued", message="Ingestion job queued.")


@router.post("/ingest/restart", response_model=IngestResponse, dependencies=[Depends(verify_api_key)])
async def restart_ingest_documents() -> IngestResponse:
    """Queue a Celery restart-ingest task (full re-ingestion) and return immediately.

    Returns:
        IngestResponse confirming the restart job was queued.
    """
    from src.worker.tasks import restart_ingest

    restart_ingest.delay()
    return IngestResponse(status="queued", message="Restart ingestion job queued.")


@router.get("/files/{drive_file_id}/open")
async def open_file(request: Request, drive_file_id: str) -> Response:
    """Stream a raw file directly from MinIO with its original MIME type for in-browser viewing.

    Args:
        request: Incoming FastAPI request carrying app state and headers.
        drive_file_id: Unique identifier of the file to open.

    Returns:
        HTTP Response with the raw file bytes and appropriate Content-Disposition header.

    Raises:
        HTTPException: 401 if the API key check fails.
        HTTPException: 404 if the file record or raw object is not found.
    """
    from src.metadata.repository import MetadataRepository

    _verify_api_key_for_file_open(request)

    settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        file_record = await repo.get_file(drive_file_id)

    if file_record is None:
        raise HTTPException(status_code=404, detail="File record not found")

    minio_raw_key = getattr(file_record, "minio_raw_key", None)
    if not minio_raw_key:
        raise HTTPException(status_code=404, detail="Raw file not available")

    storage = MinIOStorage(settings)
    try:
        raw_bytes = storage.download(settings.minio_bucket_raw, minio_raw_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Raw file object not found in storage") from exc

    file_name = (getattr(file_record, "name", None) or drive_file_id).replace('"', "")
    mime_type = getattr(file_record, "mime_type", None) or "application/octet-stream"
    return Response(
        content=raw_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'inline; filename="{file_name}"'},
    )


@router.get("/status", response_model=StatusResponse, dependencies=[Depends(verify_api_key)])
async def get_status(request: Request) -> StatusResponse:
    """Return aggregate file counts grouped by pipeline status.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        StatusResponse with total and per-status file counts.
    """
    from src.metadata.repository import MetadataRepository

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)  # Assuming None lists all

    counts = {
        "pending": 0,
        "downloaded": 0,
        "converted": 0,
        "embedded": 0,
        "failed": 0,
        "skipped": 0,
        "vision_pending": 0,
        "vision_processing": 0,
        "vision_failed": 0,
    }
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
        vision_pending=counts["vision_pending"],
        vision_processing=counts["vision_processing"],
        vision_failed=counts["vision_failed"],
    )


@router.get("/status/files", response_model=list[FileStatusItem], dependencies=[Depends(verify_api_key)])
async def get_status_files(request: Request) -> list[FileStatusItem]:
    """Return per-file processing status including MinIO text availability.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        List of FileStatusItem records for all tracked files.
    """
    from src.metadata.repository import MetadataRepository

    settings = request.app.state.settings
    storage = MinIOStorage(settings)

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)

    payload: list[FileStatusItem] = []
    for f in files:
        raw_text_available, raw_text_missing_reason = _raw_text_availability(
            storage, settings.minio_bucket_text, f.minio_text_key
        )
        payload.append(
            FileStatusItem(
                drive_file_id=f.drive_file_id,
                name=f.name,
                mime_type=f.mime_type,
                status=f.status,
                error_message=f.error_message,
                chunk_count=f.chunk_count,
                last_processed_at=str(f.last_processed_at) if f.last_processed_at else None,
                raw_text_available=raw_text_available,
                raw_text_missing_reason=raw_text_missing_reason,
            )
        )
    return payload


@router.get("/status/raw-data", response_model=list[RawDataItem], dependencies=[Depends(verify_api_key)])
async def get_status_raw_data(request: Request) -> list[RawDataItem]:
    """Return all file records with their extracted text previews from MinIO.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        List of RawDataItem records with file metadata and truncated extracted text.
    """
    from src.metadata.repository import MetadataRepository

    settings = request.app.state.settings
    storage = MinIOStorage(settings)

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        files = await repo.list_by_status(None)

    payload: list[RawDataItem] = []
    for file_record in files:
        extracted_text = None
        minio_text_key = getattr(file_record, "minio_text_key", None)
        if minio_text_key:
            try:
                raw_bytes = storage.download(settings.minio_bucket_text, minio_text_key)
                extracted_text = _safe_decode_extracted_text(raw_bytes)
            except Exception:
                extracted_text = None

        payload.append(
            RawDataItem(
                drive_file_id=file_record.drive_file_id,
                name=file_record.name,
                mime_type=file_record.mime_type,
                status=file_record.status,
                last_processed_at=str(file_record.last_processed_at) if file_record.last_processed_at else None,
                extracted_text=extracted_text,
            )
        )

    return payload
