from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, RowMapping

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
class FileRecord:
    drive_file_id: str
    name: str
    mime_type: str
    minio_raw_key: str | None
    raw_source_version: str | None
    raw_checksum: str | None
    raw_status: str


class MetadataRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_file(self, drive_file_id: str) -> FileRecord | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        drive_file_id,
                        name,
                        mime_type,
                        minio_raw_key,
                        raw_source_version,
                        raw_checksum,
                        COALESCE(raw_status, 'pending') AS raw_status
                    FROM file_records
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {"drive_file_id": drive_file_id},
            ).mappings().first()
        if row is None:
            return None
        return _map_row(row)

    def upsert_file(self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO file_records
                        (
                            drive_file_id,
                            name,
                            mime_type,
                            drive_modified_at,
                            status,
                            chunk_count,
                            raw_status,
                            text_status
                        )
                    VALUES
                        (
                            :drive_file_id,
                            :name,
                            :mime_type,
                            :drive_modified_at,
                            'pending',
                            0,
                            'pending',
                            'pending'
                        )
                    ON CONFLICT (drive_file_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        mime_type = EXCLUDED.mime_type,
                        drive_modified_at = EXCLUDED.drive_modified_at
                    """
                ),
                {
                    "drive_file_id": drive_file_id,
                    "name": name,
                    "mime_type": mime_type,
                    "drive_modified_at": drive_modified_at,
                },
            )

    def update_raw_stage(
        self,
        drive_file_id: str,
        *,
        minio_raw_key: str,
        raw_source_version: str,
        raw_checksum: str,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE file_records
                    SET
                        minio_raw_key = :minio_raw_key,
                        raw_source_version = :raw_source_version,
                        raw_checksum = :raw_checksum,
                        raw_status = 'synced',
                        raw_synced_at = :raw_synced_at,
                        status = 'downloaded',
                        text_status = 'pending',
                        text_error = NULL
                    WHERE drive_file_id = :drive_file_id
                    """
                ),
                {
                    "drive_file_id": drive_file_id,
                    "minio_raw_key": minio_raw_key,
                    "raw_source_version": raw_source_version,
                    "raw_checksum": raw_checksum,
                    "raw_synced_at": datetime.now(timezone.utc),
                },
            )

    def list_all(self) -> Sequence[FileRecord]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        drive_file_id,
                        name,
                        mime_type,
                        minio_raw_key,
                        raw_source_version,
                        raw_checksum,
                        COALESCE(raw_status, 'pending') AS raw_status
                    FROM file_records
                    """
                )
            ).mappings().all()
        return [_map_row(r) for r in rows]


def create_repository(settings: Settings) -> MetadataRepository:
    engine = create_engine(settings.database_url_sync.get_secret_value())
    _assert_schema_compatible(engine)
    return MetadataRepository(engine)


def _map_row(row: RowMapping) -> FileRecord:
    return FileRecord(
        drive_file_id=row["drive_file_id"],
        name=row["name"],
        mime_type=row["mime_type"],
        minio_raw_key=row["minio_raw_key"],
        raw_source_version=row["raw_source_version"],
        raw_checksum=row["raw_checksum"],
        raw_status=row["raw_status"],
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
            + ". Run root schema initialization/migration before starting ingest_raw."
        )
