from __future__ import annotations

from typing import List, Optional
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


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceReference]
    conversation_id: str


class GenerateSQLRequest(BaseModel):
    description: str = Field(..., min_length=1)
    target_db: str = "postgres"


class GenerateSQLResponse(BaseModel):
    job_id: str
    status: str  # pending | completed | failed
    schema_sql: Optional[str] = None
    insert_count: Optional[int] = None
    error: Optional[str] = None


class AutomationRequest(BaseModel):
    yaml_config: str


class AutomationResponse(BaseModel):
    name: str
    trigger: str
    status: str  # created | error
    message: Optional[str] = None


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
    error_message: Optional[str]
    chunk_count: int
    last_processed_at: Optional[str]
