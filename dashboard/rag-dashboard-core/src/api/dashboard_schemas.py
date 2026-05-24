"""Pydantic models for the dashboard control panel API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InFlightFile(BaseModel):
    """Minimal info about the file currently being processed in a pipeline stage."""

    name: str
    drive_file_id: str
    minio_key: str = ""
    minio_bucket: str = ""


class DashboardCardCounts(BaseModel):
    """Aggregated counters displayed on the horizontal dashboard cards."""

    source_total: int | None = Field(
        description="File count at the configured source (local folder or None if not enumerated)"
    )
    minio_raw_total: int = 0
    minio_text_total: int = 0
    raw_pending: int = 0
    raw_synced: int = 0
    transform_total: int = 0
    transform_done: int = 0
    text_ready: int = 0
    text_pending: int = 0
    text_failed: int = 0
    text_processing_now: int = 0
    postgres_total: int = 0
    postgres_missing: int = 0
    postgres_to_reprocess: int = 0
    milvus_vectors: int = 0
    milvus_files_vectorized: int = 0
    milvus_pending_files: int = 0
    vision_pending_files: int = 0
    vision_processing_files: int = 0
    sessions_legacy: int = 0
    sessions_chatbot_v2: int = 0


class DashboardState(BaseModel):
    """Full GET /dashboard/state payload."""

    cards: DashboardCardCounts
    source_url: str = ""
    ingest_processing: bool = False
    transform_processing: bool = False
    vectorize_processing: bool = False
    transform_inflight_file: InFlightFile | None = None
    milvus_inflight_file: InFlightFile | None = None
    updated_at: datetime


class DashboardActionResult(BaseModel):
    """Response for destructive POST actions."""

    status: Literal["queued", "started", "skipped", "ok"]
    detail: str = ""
    job_ids: list[str] = Field(default_factory=list)
