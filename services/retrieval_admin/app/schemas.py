from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    top_k: int = Field(default=10, ge=1, le=50)
    document_type: Optional[str] = None
    # Licitación slug. The collection is resolved server-side from the registry; when
    # omitted the search targets the global (public) collection for back-compat.
    licitacion: Optional[str] = None


class SourceReference(BaseModel):
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    text_preview: str
    score: float
    file_url: str | None = None


class RetrieveResponse(BaseModel):
    query: str
    context: str
    sources: list[SourceReference]


class AnswerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    context: str = Field(..., min_length=1)


class AnswerResponse(BaseModel):
    answer: str


class StatusResponse(BaseModel):
    total_files: int
    pending: int
    downloaded: int
    converted: int
    embedded: int
    failed: int
    vision_pending: int = 0
    vision_processing: int = 0
    vision_failed: int = 0


class FileStatusItem(BaseModel):
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    error_message: str | None
    chunk_count: int
    last_processed_at: str | None
    raw_text_available: bool
    raw_text_missing_reason: str | None


class RawDataItem(BaseModel):
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    last_processed_at: str | None
    extracted_text: str | None
