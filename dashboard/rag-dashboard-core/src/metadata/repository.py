from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, delete, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


def _dialect_name_for_session(session: AsyncSession | Session) -> str:
    bind = session.bind
    if bind is None:
        return "sqlite"
    return bind.dialect.name


def _upsert_insert_for_session(session: AsyncSession | Session, model: type[Base]):
    if _dialect_name_for_session(session) == "postgresql":
        return postgresql_insert(model)
    return sqlite_insert(model)


class FileRecord(Base):
    __tablename__ = "file_records"

    drive_file_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    drive_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minio_raw_key: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_text_key: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_status: Mapped[str] = mapped_column(String, default="pending")
    text_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text_source_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    text_status: Mapped[str] = mapped_column(String, default="pending")
    text_error: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class SyncState(Base):
    """Stores the Google Drive changes.list page token for incremental sync."""

    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String, primary_key=True, default="drive_page_token")
    value: Mapped[str] = mapped_column(String, nullable=False, default="")


class DriveConnection(Base):
    """Single-tenant Google OAuth connection (one row)."""

    __tablename__ = "drive_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected_folder_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractedDocument(Base):
    """Structured key-value pairs produced by the VLM extractor.

    Hybrid schema: a handful of fixed columns enable cheap SQL filtering
    on common business fields (issuer, date, amount), while `extras` and
    `parties` use JSON for everything else. On Postgres the JSON columns
    map to `jsonb`; on SQLite they fall back to a TEXT JSON column so
    unit tests can keep using aiosqlite.
    """

    __tablename__ = "extracted_documents"

    drive_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("file_records.drive_file_id", ondelete="CASCADE"), primary_key=True
    )
    document_type: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer: Mapped[str | None] = mapped_column(String, nullable=True)
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    parties: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    extras: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class MetadataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_file_record(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> FileRecord:
        record = FileRecord(
            drive_file_id=drive_file_id,
            name=name,
            mime_type=mime_type,
            drive_modified_at=drive_modified_at,
            status="pending",
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get_file(self, drive_file_id: str) -> FileRecord | None:
        result = await self._session.execute(select(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        return result.scalar_one_or_none()

    async def update_status(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(status=status, error_message=error_message)
        )
        await self._session.commit()

    async def update_last_processed_at(self, drive_file_id: str) -> None:
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(last_processed_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def list_by_status(self, status: str | None) -> Sequence[FileRecord]:
        if status is None:
            result = await self._session.execute(select(FileRecord))
        else:
            result = await self._session.execute(select(FileRecord).where(FileRecord.status == status))
        return result.scalars().all()

    async def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        stmt = _upsert_insert_for_session(self._session, FileRecord).values(
            drive_file_id=drive_file_id,
            name=name,
            mime_type=mime_type,
            drive_modified_at=drive_modified_at,
            status="pending",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["drive_file_id"],
            set_={
                "name": stmt.excluded.name,
                "mime_type": stmt.excluded.mime_type,
                "drive_modified_at": stmt.excluded.drive_modified_at,
                "status": "pending",
                "raw_status": "pending",
                "text_status": "pending",
                "text_error": None,
            },
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def update_raw_stage(
        self,
        drive_file_id: str,
        *,
        minio_raw_key: str | None = None,
        raw_source_version: str | None = None,
        raw_checksum: str | None = None,
        raw_status: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if minio_raw_key is not None:
            values["minio_raw_key"] = minio_raw_key
        if raw_source_version is not None:
            values["raw_source_version"] = raw_source_version
        if raw_checksum is not None:
            values["raw_checksum"] = raw_checksum
        if raw_status is not None:
            values["raw_status"] = raw_status
        if raw_status == "synced":
            values["raw_synced_at"] = datetime.now(timezone.utc)
        if values:
            await self._session.execute(update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(**values))
            await self._session.commit()

    async def update_text_stage(
        self,
        drive_file_id: str,
        *,
        minio_text_key: str | None = None,
        text_source_checksum: str | None = None,
        text_checksum: str | None = None,
        text_status: str | None = None,
        text_error: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if minio_text_key is not None:
            values["minio_text_key"] = minio_text_key
        if text_source_checksum is not None:
            values["text_source_checksum"] = text_source_checksum
        if text_checksum is not None:
            values["text_checksum"] = text_checksum
        if text_status is not None:
            values["text_status"] = text_status
        values["text_error"] = text_error
        if text_status == "ready_for_embedding":
            values["text_extracted_at"] = datetime.now(timezone.utc)
        if values:
            await self._session.execute(update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(**values))
            await self._session.commit()

    async def list_ready_for_embedding(self) -> Sequence[FileRecord]:
        result = await self._session.execute(
            select(FileRecord).where(FileRecord.text_status == "ready_for_embedding")
        )
        return result.scalars().all()

    async def update_chunk_count(self, drive_file_id: str, count: int) -> None:
        await self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(chunk_count=count)
        )
        await self._session.commit()

    async def update_text_key(self, drive_file_id: str, minio_text_key: str) -> None:
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(minio_text_key=minio_text_key)
        )
        await self._session.commit()

    async def update_raw_key(self, drive_file_id: str, minio_raw_key: str) -> None:
        await self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(minio_raw_key=minio_raw_key)
        )
        await self._session.commit()

    async def get_page_token(self) -> str:
        result = await self._session.execute(select(SyncState).where(SyncState.key == "drive_page_token"))
        state = result.scalar_one_or_none()
        if not state:
            state = SyncState(key="drive_page_token", value="")
            self._session.add(state)
            await self._session.commit()
            await self._session.refresh(state)
        return state.value

    async def update_page_token(self, token: str) -> None:
        stmt = _upsert_insert_for_session(self._session, SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        await self._session.execute(stmt)
        await self._session.commit()

    async def delete_file_record(self, drive_file_id: str) -> None:
        await self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        await self._session.commit()

    async def delete_all_file_records(self) -> None:
        await self._session.execute(delete(FileRecord))
        await self._session.commit()

    async def get_drive_connection(self) -> DriveConnection | None:
        result = await self._session.execute(select(DriveConnection).limit(1))
        return result.scalar_one_or_none()

    async def save_drive_oauth_token(self, refresh_token_enc: str) -> None:
        row = await self.get_drive_connection()
        now = datetime.now(timezone.utc)
        if row is None:
            row = DriveConnection(refresh_token_enc=refresh_token_enc, selected_folder_id="", updated_at=now)
            self._session.add(row)
        else:
            row.refresh_token_enc = refresh_token_enc
            row.updated_at = now
        await self._session.commit()

    async def set_drive_selected_folder(self, folder_id: str) -> None:
        row = await self.get_drive_connection()
        now = datetime.now(timezone.utc)
        if row is None:
            row = DriveConnection(refresh_token_enc="", selected_folder_id=folder_id, updated_at=now)
            self._session.add(row)
        else:
            row.selected_folder_id = folder_id
            row.updated_at = now
        await self._session.commit()

    async def upsert_extracted_document(
        self,
        drive_file_id: str,
        *,
        document_type: str | None = None,
        issuer: str | None = None,
        issued_at: date | None = None,
        total_amount: Decimal | None = None,
        currency: str | None = None,
        parties: list[str] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        values = dict(
            drive_file_id=drive_file_id,
            document_type=document_type,
            issuer=issuer,
            issued_at=issued_at,
            total_amount=total_amount,
            currency=currency,
            parties=list(parties or []),
            extras=dict(extras or {}),
            extracted_at=datetime.now(timezone.utc),
        )
        stmt = _upsert_insert_for_session(self._session, ExtractedDocument).values(**values)
        update_set = {k: stmt.excluded[k] for k in values if k != "drive_file_id"}
        stmt = stmt.on_conflict_do_update(index_elements=["drive_file_id"], set_=update_set)
        await self._session.execute(stmt)
        await self._session.commit()

    async def get_extracted_document(self, drive_file_id: str) -> ExtractedDocument | None:
        result = await self._session.execute(
            select(ExtractedDocument).where(ExtractedDocument.drive_file_id == drive_file_id)
        )
        return result.scalar_one_or_none()

    async def get_inflight_files(self) -> dict[str, dict | None]:
        """Return the first file being text-processed and the first queued for embedding."""
        transform_row = (
            await self._session.execute(
                text(
                    "SELECT name, drive_file_id, minio_raw_key FROM file_records "
                    "WHERE text_status = 'processing' LIMIT 1"
                )
            )
        ).mappings().first()

        milvus_row = (
            await self._session.execute(
                text(
                    "SELECT name, drive_file_id, minio_text_key FROM file_records "
                    "WHERE text_status = 'embedding_queued' LIMIT 1"
                )
            )
        ).mappings().first()

        return {
            "transform": dict(transform_row) if transform_row else None,
            "milvus": dict(milvus_row) if milvus_row else None,
        }

    async def get_dashboard_counts(self) -> dict[str, int]:
        """Single-query aggregates for GET /dashboard/state (Postgres + SQLite tests)."""
        query = text(
            """
            SELECT
                COUNT(*) AS postgres_total,
                SUM(CASE WHEN raw_status = 'synced' THEN 1 ELSE 0 END) AS raw_synced,
                SUM(CASE WHEN COALESCE(raw_status, 'pending') = 'pending' THEN 1 ELSE 0 END) AS raw_pending,
                SUM(CASE WHEN text_status = 'ready_for_embedding' THEN 1 ELSE 0 END) AS text_ready,
                SUM(
                    CASE
                        WHEN raw_status = 'synced' AND text_status IN ('pending', 'failed') THEN 1
                        ELSE 0
                    END
                ) AS text_pending,
                SUM(CASE WHEN text_status = 'processing' THEN 1 ELSE 0 END) AS text_processing_now,
                SUM(CASE WHEN text_status = 'failed' THEN 1 ELSE 0 END) AS text_failed,
                SUM(CASE WHEN raw_status = 'synced' THEN 1 ELSE 0 END) AS transform_total,
                SUM(
                    CASE
                        WHEN raw_status = 'synced'
                            AND text_status IN ('ready_for_embedding', 'embedded', 'embedding_queued', 'vision_pending')
                        THEN 1
                        ELSE 0
                    END
                ) AS transform_done,
                SUM(CASE WHEN status = 'embedded' THEN 1 ELSE 0 END) AS milvus_files_vectorized,
                SUM(
                    CASE
                        WHEN status IN ('failed', 'vision_failed') OR text_status = 'failed' THEN 1
                        ELSE 0
                    END
                ) AS postgres_to_reprocess,
                SUM(
                    CASE
                        WHEN text_status IN ('ready_for_embedding', 'embedding_queued')
                            AND COALESCE(status, '') <> 'embedded'
                        THEN 1
                        ELSE 0
                    END
                ) AS milvus_pending_files,
                SUM(CASE WHEN status IN ('vision_pending', 'vision_processing') THEN 1 ELSE 0 END) AS vision_pending_files,
                SUM(CASE WHEN status = 'vision_processing' THEN 1 ELSE 0 END) AS vision_processing_files
            FROM file_records
            """
        )
        row = (await self._session.execute(query)).mappings().first()
        if not row:
            return {
                "postgres_total": 0,
                "raw_synced": 0,
                "raw_pending": 0,
                "text_ready": 0,
                "text_pending": 0,
                "text_processing_now": 0,
                "text_failed": 0,
                "transform_total": 0,
                "transform_done": 0,
                "milvus_files_vectorized": 0,
                "postgres_to_reprocess": 0,
                "milvus_pending_files": 0,
                "vision_pending_files": 0,
                "vision_processing_files": 0,
            }
        return {k: int(row[k] or 0) for k in row.keys()}


class SyncMetadataRepository:
    """Synchronous version of MetadataRepository for Celery tasks."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_file_record(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> FileRecord:
        record = FileRecord(
            drive_file_id=drive_file_id,
            name=name,
            mime_type=mime_type,
            drive_modified_at=drive_modified_at,
            status="pending",
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return record

    async def get_file(self, drive_file_id: str) -> FileRecord | None:
        return self._session.execute(
            select(FileRecord).where(FileRecord.drive_file_id == drive_file_id)
        ).scalar_one_or_none()

    def update_status_sync(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(status=status, error_message=error_message)
        )
        self._session.commit()

    def mark_embedding_failure_sync(self, drive_file_id: str, error_message: str) -> None:
        """Handle permanent embedding task failure.

        If the file was in an embedding state (queued or embedded), reset it to
        'ready_for_embedding' so the next poll cycle retries it automatically.
        Otherwise fall back to marking it as failed.
        """
        self._session.execute(
            text(
                """
                UPDATE file_records
                SET
                    status = CASE
                        WHEN text_status IN ('embedding_queued', 'embedded') THEN 'converted'
                        ELSE 'failed'
                    END,
                    error_message = :error,
                    text_status = CASE
                        WHEN text_status IN ('embedding_queued', 'embedded') THEN 'ready_for_embedding'
                        ELSE text_status
                    END
                WHERE drive_file_id = :id
                """
            ),
            {"id": drive_file_id, "error": error_message[:4000]},
        )
        self._session.commit()

    async def update_status(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        self.update_status_sync(drive_file_id, status, error_message)

    def update_last_processed_at(self, drive_file_id: str) -> None:
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(last_processed_at=datetime.now(timezone.utc))
        )
        self._session.commit()

    def list_by_status(self, status: str | None) -> Sequence[FileRecord]:
        if status is None:
            return self._session.execute(select(FileRecord)).scalars().all()
        return self._session.execute(select(FileRecord).where(FileRecord.status == status)).scalars().all()

    async def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        stmt = _upsert_insert_for_session(self._session, FileRecord).values(
            drive_file_id=drive_file_id,
            name=name,
            mime_type=mime_type,
            drive_modified_at=drive_modified_at,
            status="pending",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["drive_file_id"],
            set_={
                "name": stmt.excluded.name,
                "mime_type": stmt.excluded.mime_type,
                "drive_modified_at": stmt.excluded.drive_modified_at,
                "status": "pending",
                "raw_status": "pending",
                "text_status": "pending",
                "text_error": None,
            },
        )
        self._session.execute(stmt)
        self._session.commit()

    def update_raw_stage_sync(
        self,
        drive_file_id: str,
        *,
        minio_raw_key: str | None = None,
        raw_source_version: str | None = None,
        raw_checksum: str | None = None,
        raw_status: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if minio_raw_key is not None:
            values["minio_raw_key"] = minio_raw_key
        if raw_source_version is not None:
            values["raw_source_version"] = raw_source_version
        if raw_checksum is not None:
            values["raw_checksum"] = raw_checksum
        if raw_status is not None:
            values["raw_status"] = raw_status
        if raw_status == "synced":
            values["raw_synced_at"] = datetime.now(timezone.utc)
        if values:
            self._session.execute(update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(**values))
            self._session.commit()

    def update_text_stage_sync(
        self,
        drive_file_id: str,
        *,
        minio_text_key: str | None = None,
        text_source_checksum: str | None = None,
        text_checksum: str | None = None,
        text_status: str | None = None,
        text_error: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if minio_text_key is not None:
            values["minio_text_key"] = minio_text_key
        if text_source_checksum is not None:
            values["text_source_checksum"] = text_source_checksum
        if text_checksum is not None:
            values["text_checksum"] = text_checksum
        if text_status is not None:
            values["text_status"] = text_status
        values["text_error"] = text_error
        if text_status == "ready_for_embedding":
            values["text_extracted_at"] = datetime.now(timezone.utc)
        if values:
            self._session.execute(update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(**values))
            self._session.commit()

    def list_ready_for_embedding_sync(self) -> Sequence[FileRecord]:
        return (
            self._session.execute(
                select(FileRecord).where(FileRecord.text_status == "ready_for_embedding")
            )
            .scalars()
            .all()
        )

    def reset_stale_embedding_queued_sync(self, stale_after_seconds: int) -> int:
        """Reset embedding_queued files that have been stuck longer than stale_after_seconds.

        Covers the case where a Celery worker or broker dies after the file is
        marked embedding_queued but before the task runs — on_failure never fires
        and the poll loop never picks the file up again without this reset.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        result = self._session.execute(
            text(
                """
                UPDATE file_records
                SET text_status = 'ready_for_embedding',
                    text_error = 'auto-reset: stuck in embedding_queued'
                WHERE text_status = 'embedding_queued'
                  AND text_extracted_at < :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
        self._session.commit()
        return result.rowcount

    def list_vision_pending_sync(self) -> Sequence[FileRecord]:
        return (
            self._session.execute(
                select(FileRecord).where(FileRecord.status == "vision_pending")
            )
            .scalars()
            .all()
        )

    def update_chunk_count(self, drive_file_id: str, count: int) -> None:
        self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(chunk_count=count)
        )
        self._session.commit()

    def update_text_key_sync(self, drive_file_id: str, minio_text_key: str) -> None:
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(minio_text_key=minio_text_key)
        )
        self._session.commit()

    def update_raw_key_sync(self, drive_file_id: str, minio_raw_key: str) -> None:
        self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(minio_raw_key=minio_raw_key)
        )
        self._session.commit()

    async def get_page_token(self) -> str:
        state = self._session.execute(select(SyncState).where(SyncState.key == "drive_page_token")).scalar_one_or_none()
        if not state:
            state = SyncState(key="drive_page_token", value="")
            self._session.add(state)
            self._session.commit()
            self._session.refresh(state)
        return state.value

    async def update_page_token(self, token: str) -> None:
        stmt = _upsert_insert_for_session(self._session, SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        self._session.execute(stmt)
        self._session.commit()

    def delete_file_record_sync(self, drive_file_id: str) -> None:
        self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        self._session.commit()

    async def delete_file_record(self, drive_file_id: str) -> None:
        self.delete_file_record_sync(drive_file_id)

    def get_drive_connection_sync(self) -> DriveConnection | None:
        return self._session.execute(select(DriveConnection).limit(1)).scalar_one_or_none()

    def delete_all_file_records_sync(self) -> None:
        self._session.execute(delete(FileRecord))
        self._session.commit()

    def upsert_extracted_document_sync(
        self,
        drive_file_id: str,
        *,
        document_type: str | None = None,
        issuer: str | None = None,
        issued_at: date | None = None,
        total_amount: Decimal | None = None,
        currency: str | None = None,
        parties: list[str] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        values = dict(
            drive_file_id=drive_file_id,
            document_type=document_type,
            issuer=issuer,
            issued_at=issued_at,
            total_amount=total_amount,
            currency=currency,
            parties=list(parties or []),
            extras=dict(extras or {}),
            extracted_at=datetime.now(timezone.utc),
        )
        stmt = _upsert_insert_for_session(self._session, ExtractedDocument).values(**values)
        update_set = {k: stmt.excluded[k] for k in values if k != "drive_file_id"}
        stmt = stmt.on_conflict_do_update(index_elements=["drive_file_id"], set_=update_set)
        self._session.execute(stmt)
        self._session.commit()

    def get_extracted_document_sync(self, drive_file_id: str) -> ExtractedDocument | None:
        return self._session.execute(
            select(ExtractedDocument).where(ExtractedDocument.drive_file_id == drive_file_id)
        ).scalar_one_or_none()


async def init_db(database_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_file_record_stage_columns)
    await engine.dispose()


def _ensure_file_record_stage_columns(conn) -> None:
    """Backfill stage-tracking columns for existing deployments.

    SQLAlchemy's create_all does not ALTER existing tables, so we add any
    missing columns in-place to keep upgrades backwards compatible.
    """
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("file_records")}
    required: dict[str, str] = {
        "raw_source_version": "VARCHAR",
        "raw_checksum": "VARCHAR(128)",
        "raw_synced_at": "TIMESTAMP",
        "raw_status": "VARCHAR DEFAULT 'pending'",
        "text_checksum": "VARCHAR(128)",
        "text_source_checksum": "VARCHAR(128)",
        "text_extracted_at": "TIMESTAMP",
        "text_status": "VARCHAR DEFAULT 'pending'",
        "text_error": "TEXT",
    }
    for column_name, column_type in required.items():
        if column_name in existing:
            continue
        conn.execute(text(f"ALTER TABLE file_records ADD COLUMN {column_name} {column_type}"))
