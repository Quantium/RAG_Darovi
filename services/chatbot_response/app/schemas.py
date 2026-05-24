from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    conversation_id: Optional[str] = None
    document_type: Optional[str] = None


class SourceReference(BaseModel):
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    text_preview: str
    score: float
    file_url: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    conversation_id: str


class RetrieveResponse(BaseModel):
    query: str
    context: str
    sources: list[SourceReference]
