from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine, RowMapping

from .settings import Settings

FILE_RECORD_SCHEMA_COLUMNS: set[str] = {
    "drive_file_id",
    "name",
    "mime_type",
    "drive_modified_at",
    "status",
    "error_message",
    "chunk_count",
    "last_processed_at",
    "minio_raw_key",
    "minio_text_key",
    "raw_source_version",
    "raw_checksum",
    "raw_synced_at",
    "raw_status",
    "text_checksum",
    "text_source_checksum",
    "text_extracted_at",
    "text_status",
    "text_error",
}


@dataclass
class RawCandidate:
    drive_file_id: str
    name: str
    mime_type: str
    minio_raw_key: str
    raw_checksum: str


class MetadataRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock_conn: Connection | None = None

    def try_acquire_lock(self, lock_id: int) -> bool:
        if self._engine.dialect.name != "postgresql":
            return True
        conn = self._engine.connect()
        ok = conn.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}).scalar_one()
        if ok:
            self._lock_conn = conn
            return True
        conn.close()
        return False

    def release_lock(self, lock_id: int) -> None:
        if self._engine.dialect.name != "postgresql":
            return
        if self._lock_conn is None:
            return
        try:
            self._lock_conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
        finally:
            self._lock_conn.close()
            self._lock_conn = None

    def list_raw_changed_candidates(self, batch_size: int) -> Sequence[RawCandidate]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        drive_file_id,
                        name,
                        mime_type,
                        minio_raw_key,
                        raw_checksum
                    FROM file_records
                    WHERE
                        raw_status = 'synced'
                        AND minio_raw_key IS NOT NULL
                        AND raw_checksum IS NOT NULL
                        AND (
                            text_source_checksum IS NULL
                            OR text_source_checksum <> raw_checksum
                            OR text_status IN ('pending', 'failed', 'processing')
                        )
                    ORDER BY drive_file_id
                    LIMIT :batch_size
                    """
                ),
                {"batch_size": batch_size},
            ).mappings().all()
        return [_map_candidate(r) for r in rows]

    def mark_text_processing(self, drive_file_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE file_records
                    SET text_status = 'processing', text_error = NULL
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {"drive_file_id": drive_file_id},
            )

    def mark_text_ready(
        self,
        drive_file_id: str,
        *,
        minio_text_key: str,
        text_source_checksum: str,
        text_checksum: str,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE file_records
                    SET
                        minio_text_key = :minio_text_key,
                        text_source_checksum = :text_source_checksum,
                        text_checksum = :text_checksum,
                        text_status = 'ready_for_embedding',
                        text_error = NULL,
                        text_extracted_at = :text_extracted_at,
                        status = 'converted'
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {
                    "drive_file_id": drive_file_id,
                    "minio_text_key": minio_text_key,
                    "text_source_checksum": text_source_checksum,
                    "text_checksum": text_checksum,
                    "text_extracted_at": datetime.now(timezone.utc),
                },
            )

    def mark_text_vision_pending(
        self,
        drive_file_id: str,
        *,
        minio_text_key: str,
        text_source_checksum: str,
        text_checksum: str,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE file_records
                    SET
                        minio_text_key = :minio_text_key,
                        text_source_checksum = :text_source_checksum,
                        text_checksum = :text_checksum,
                        text_status = 'vision_pending',
                        text_error = NULL,
                        text_extracted_at = :text_extracted_at,
                        status = 'vision_pending'
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {
                    "drive_file_id": drive_file_id,
                    "minio_text_key": minio_text_key,
                    "text_source_checksum": text_source_checksum,
                    "text_checksum": text_checksum,
                    "text_extracted_at": datetime.now(timezone.utc),
                },
            )

    def mark_text_failed(self, drive_file_id: str, error_message: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE file_records
                    SET
                        text_status = 'failed',
                        text_error = :text_error,
                        status = 'failed'
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {"drive_file_id": drive_file_id, "text_error": error_message[:4000]},
            )


def create_repository(settings: Settings) -> MetadataRepository:
    engine = create_engine(settings.database_url_sync.get_secret_value())
    _assert_schema_compatible(engine)
    return MetadataRepository(engine)


def _map_candidate(row: RowMapping) -> RawCandidate:
    return RawCandidate(
        drive_file_id=row["drive_file_id"],
        name=row["name"],
        mime_type=row["mime_type"],
        minio_raw_key=row["minio_raw_key"],
        raw_checksum=row["raw_checksum"],
    )


def _assert_schema_compatible(engine: Engine) -> None:
    """Fail fast if file_records schema diverges from root project contract."""
    inspector = inspect(engine)
    if "file_records" not in inspector.get_table_names():
        raise RuntimeError("Required table 'file_records' is missing.")
    existing_columns = {col["name"] for col in inspector.get_columns("file_records")}
    missing = sorted(FILE_RECORD_SCHEMA_COLUMNS - existing_columns)
    if missing:
        raise RuntimeError(
            "Schema mismatch for file_records. Missing columns: "
            + ", ".join(missing)
            + ". Run root schema initialization/migration before starting extract_text."
        )
