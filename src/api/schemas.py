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
    # Files whose converter dropped VLM sentinels and are awaiting OCR by
    # the vision_extract task (queue=vision). These are NOT yet usable.
    vision_pending: int = 0
    # Currently being transcribed by Llama-3.2-Vision in app-worker-vision.
    vision_processing: int = 0
    # Permanent VLM failure after retries + downscale + circuit breaker.
    vision_failed: int = 0


class FileStatusItem(BaseModel):
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    error_message: Optional[str]
    chunk_count: int
    last_processed_at: Optional[str]
    raw_text_available: bool
    raw_text_missing_reason: Optional[str]


class RawDataItem(BaseModel):
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    last_processed_at: Optional[str]
    extracted_text: Optional[str]


class IngestResponse(BaseModel):
    status: str
    message: str


class DriveBootstrapResponse(BaseModel):
    ingest_source: str = "drive"
    oauth_configured: bool
    connected: bool
    folder_selected: bool
    service_account_ready: bool
    onboarding_phase: str
    chat_ready: bool
    total_files: int
    pending: int
    downloaded: int
    converted: int
    embedded: int
    failed: int
    skipped: int
    # VLM lifecycle: defaults to 0 so existing clients keep working.
    vision_pending: int = 0
    vision_processing: int = 0
    vision_failed: int = 0


class DriveFolderItem(BaseModel):
    id: str
    name: str


class SelectFolderRequest(BaseModel):
    folder_id: str = Field(..., min_length=1, max_length=512)
