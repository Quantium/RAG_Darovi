from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .llm import LLMService
from .metadata import MetadataService
from .retrieval import Retriever
from .schemas import (
    AnswerRequest,
    AnswerResponse,
    FileStatusItem,
    RawDataItem,
    RetrieveRequest,
    RetrieveResponse,
    SourceReference,
    StatusResponse,
)
from .settings import Settings


async def verify_api_key(request: Request) -> None:
    settings: Settings = request.app.state.settings
    configured = settings.api_key.get_secret_value()
    if not configured:
        return
    incoming = request.headers.get("X-API-Key") or ""
    if incoming != configured:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def create_app() -> FastAPI:
    app = FastAPI(title="Retrieval Admin Service", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    settings = Settings()
    cache = redis.Redis.from_url(settings.redis_cache_url)
    app.state.settings = settings
    app.state.metadata = MetadataService(settings)
    app.state.retriever = Retriever(settings=settings, cache=cache)
    app.state.llm = LLMService(settings)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/retrieve", response_model=RetrieveResponse, dependencies=[Depends(verify_api_key)])
    async def retrieve(body: RetrieveRequest) -> RetrieveResponse:
        retriever: Retriever = app.state.retriever
        chunks = await retriever.retrieve(body.query, top_k=body.top_k, document_type=body.document_type)
        console = settings.minio_console_endpoint.rstrip("/")
        bucket = settings.minio_bucket_raw
        sources = [
            SourceReference(
                source_file_id=c.source_file_id,
                source_name=c.source_name,
                section_title=c.section_title,
                chunk_index=c.chunk_index,
                text_preview=c.text[:200],
                score=c.score,
                file_url=f"{console}/browser/{bucket}/{quote(c.source_file_id, safe='')}/{quote(c.source_name, safe='')}",
            )
            for c in chunks
        ]
        context = "\n\n".join(f"[Source: {c.source_name} | Section: {c.section_title}]\n{c.text}" for c in chunks)
        return RetrieveResponse(query=body.query, context=context, sources=sources)

    @app.post("/answer", response_model=AnswerResponse, dependencies=[Depends(verify_api_key)])
    async def answer(body: AnswerRequest) -> AnswerResponse:
        llm: LLMService = app.state.llm
        text = await llm.answer(body.query, body.context)
        return AnswerResponse(answer=text)

    @app.get("/status", response_model=StatusResponse, dependencies=[Depends(verify_api_key)])
    async def status() -> StatusResponse:
        metadata: MetadataService = app.state.metadata
        counts = await metadata.get_status_counts()
        return StatusResponse(**counts)

    @app.get("/status/files", response_model=list[FileStatusItem], dependencies=[Depends(verify_api_key)])
    async def status_files() -> list[FileStatusItem]:
        metadata: MetadataService = app.state.metadata
        rows = await metadata.list_files()
        payload: list[FileStatusItem] = []
        for row in rows:
            available, reason = metadata.raw_text_available(row.minio_text_key)
            payload.append(
                FileStatusItem(
                    drive_file_id=row.drive_file_id,
                    name=row.name,
                    mime_type=row.mime_type,
                    status=row.status,
                    error_message=row.error_message,
                    chunk_count=row.chunk_count,
                    last_processed_at=row.last_processed_at,
                    raw_text_available=available,
                    raw_text_missing_reason=reason,
                )
            )
        return payload

    @app.get("/status/raw-data", response_model=list[RawDataItem], dependencies=[Depends(verify_api_key)])
    async def status_raw_data() -> list[RawDataItem]:
        metadata: MetadataService = app.state.metadata
        rows = await metadata.list_raw_data()
        return [RawDataItem(**row) for row in rows]

    @app.on_event("shutdown")
    async def shutdown() -> None:
        metadata: MetadataService = app.state.metadata
        await metadata.close()

    @app.get("/_conversation-id")
    async def conversation_id() -> dict[str, str]:
        return {"conversation_id": str(uuid4())}

    return app
