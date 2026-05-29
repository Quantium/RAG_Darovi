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
    """Return the dialect name ('postgresql', 'sqlite', etc.) for the given session.

    Args:
        session: SQLAlchemy sync or async session.

    Returns:
        Dialect name string, defaulting to 'sqlite' when the bind is None.
    """
    bind = session.bind
    if bind is None:
        return "sqlite"
    return bind.dialect.name


def _upsert_insert_for_session(session: AsyncSession | Session, model: type[Base]):
    """Return the dialect-appropriate INSERT statement class for an upsert operation.

    Args:
        session: SQLAlchemy sync or async session used to detect the dialect.
        model: ORM model class to build the insert statement for.

    Returns:
        A PostgreSQL or SQLite insert construct with on_conflict_do_update support.
    """
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
    """Stores a snapshot token used by the local folder syncer for incremental change detection."""

    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String, primary_key=True, default="drive_page_token")
    value: Mapped[str] = mapped_column(String, nullable=False, default="")


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
        """Initialize the async repository with an AsyncSession.

        Args:
            session: SQLAlchemy async database session.
        """
        self._session = session

    async def create_file_record(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> FileRecord:
        """Create a new file record with 'pending' status and return it.

        Args:
            drive_file_id: Unique source identifier for the file.
            name: Display file name.
            mime_type: MIME type string of the file.
            drive_modified_at: Last-modified timestamp from the source.

        Returns:
            The freshly committed and refreshed FileRecord instance.
        """
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
        """Fetch a single file record by its source identifier.

        Args:
            drive_file_id: Unique source identifier for the file.

        Returns:
            FileRecord if found, or None if no matching row exists.
        """
        result = await self._session.execute(select(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        return result.scalar_one_or_none()

    async def update_status(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        """Update the top-level processing status and optional error message for a file.

        Args:
            drive_file_id: Unique source identifier for the file.
            status: New pipeline status value (e.g. 'downloaded', 'embedded', 'failed').
            error_message: Optional error description to store alongside the status.
        """
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(status=status, error_message=error_message)
        )
        await self._session.commit()

    async def update_last_processed_at(self, drive_file_id: str) -> None:
        """Stamp the current UTC time as last_processed_at for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
        """
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(last_processed_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def list_by_status(self, status: str | None) -> Sequence[FileRecord]:
        """Return all file records, optionally filtered to a specific status.

        Args:
            status: Pipeline status to filter on, or None to return all records.

        Returns:
            Sequence of FileRecord instances matching the filter.
        """
        if status is None:
            result = await self._session.execute(select(FileRecord))
        else:
            result = await self._session.execute(select(FileRecord).where(FileRecord.status == status))
        return result.scalars().all()

    async def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        """Insert a new file record or reset it to 'pending' on conflict.

        Args:
            drive_file_id: Unique source identifier for the file.
            name: Display file name.
            mime_type: MIME type string of the file.
            drive_modified_at: Last-modified timestamp from the source.
        """
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
        """Patch raw-stage columns for a file record, updating only provided fields.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_raw_key: MinIO object key for the raw file, if changed.
            raw_source_version: Source version string, if changed.
            raw_checksum: SHA-256 hex digest of the raw file, if changed.
            raw_status: New raw pipeline status (e.g. 'synced'), if changed.
        """
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
        """Patch text-stage columns for a file record, updating only provided fields.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_text_key: MinIO object key for the extracted text, if changed.
            text_source_checksum: Checksum of the raw file this text was extracted from.
            text_checksum: Checksum of the extracted text content itself.
            text_status: New text pipeline status (e.g. 'ready_for_embedding').
            text_error: Error description to store, or None to clear a previous error.
        """
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
        """Return all file records with text_status='ready_for_embedding'.

        Returns:
            Sequence of FileRecord instances waiting to be embedded.
        """
        result = await self._session.execute(
            select(FileRecord).where(FileRecord.text_status == "ready_for_embedding")
        )
        return result.scalars().all()

    async def update_chunk_count(self, drive_file_id: str, count: int) -> None:
        """Update the stored chunk count for a file after embedding.

        Args:
            drive_file_id: Unique source identifier for the file.
            count: Number of embedded chunks produced from this file.
        """
        await self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(chunk_count=count)
        )
        await self._session.commit()

    async def update_text_key(self, drive_file_id: str, minio_text_key: str) -> None:
        """Update the MinIO text object key for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_text_key: New MinIO object key for the extracted text.
        """
        await self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(minio_text_key=minio_text_key)
        )
        await self._session.commit()

    async def update_raw_key(self, drive_file_id: str, minio_raw_key: str) -> None:
        """Update the MinIO raw object key for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_raw_key: New MinIO object key for the raw file.
        """
        await self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(minio_raw_key=minio_raw_key)
        )
        await self._session.commit()

    async def get_page_token(self) -> str:
        """Retrieve the current sync page token, creating a blank entry if none exists.

        Returns:
            The stored sync token string, or an empty string for the first run.
        """
        result = await self._session.execute(select(SyncState).where(SyncState.key == "drive_page_token"))
        state = result.scalar_one_or_none()
        if not state:
            state = SyncState(key="drive_page_token", value="")
            self._session.add(state)
            await self._session.commit()
            await self._session.refresh(state)
        return state.value

    async def update_page_token(self, token: str) -> None:
        """Upsert the sync page token in the sync_state table.

        Args:
            token: New page token returned by the source after a sync cycle.
        """
        stmt = _upsert_insert_for_session(self._session, SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        await self._session.execute(stmt)
        await self._session.commit()

    async def delete_file_record(self, drive_file_id: str) -> None:
        """Delete a single file record from the database.

        Args:
            drive_file_id: Unique source identifier of the file to delete.
        """
        await self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        await self._session.commit()

    async def delete_all_file_records(self) -> None:
        """Delete all file records from the database."""
        await self._session.execute(delete(FileRecord))
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
        """Insert or overwrite the extracted document record for a file.

        Args:
            drive_file_id: Unique source identifier linking this record to a file_records row.
            document_type: Optional document classification string.
            issuer: Optional issuer name from the document.
            issued_at: Optional document issuance date.
            total_amount: Optional monetary total extracted from the document.
            currency: Optional ISO-4217 currency code.
            parties: Optional list of parties named in the document.
            extras: Optional dict of additional extracted key-value fields.
        """
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
        """Fetch the extracted document record for a given file.

        Args:
            drive_file_id: Unique source identifier of the file.

        Returns:
            ExtractedDocument if it exists, or None if not yet extracted.
        """
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
        """Initialize the sync repository with a SQLAlchemy Session.

        Args:
            session: SQLAlchemy synchronous database session.
        """
        self._session = session

    def create_file_record(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> FileRecord:
        """Create a new file record with 'pending' status and return it.

        Args:
            drive_file_id: Unique source identifier for the file.
            name: Display file name.
            mime_type: MIME type string of the file.
            drive_modified_at: Last-modified timestamp from the source.

        Returns:
            The freshly committed and refreshed FileRecord instance.
        """
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
        """Fetch a single file record by its source identifier (sync session, async interface).

        Args:
            drive_file_id: Unique source identifier for the file.

        Returns:
            FileRecord if found, or None if no matching row exists.
        """
        return self._session.execute(
            select(FileRecord).where(FileRecord.drive_file_id == drive_file_id)
        ).scalar_one_or_none()

    def update_status_sync(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        """Update the top-level processing status and optional error message for a file.

        Args:
            drive_file_id: Unique source identifier for the file.
            status: New pipeline status value (e.g. 'embedded', 'failed').
            error_message: Optional error description to store alongside the status.
        """
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
        """Async-compatible wrapper that delegates to update_status_sync.

        Args:
            drive_file_id: Unique source identifier for the file.
            status: New pipeline status value.
            error_message: Optional error description.
        """
        self.update_status_sync(drive_file_id, status, error_message)

    def update_last_processed_at(self, drive_file_id: str) -> None:
        """Stamp the current UTC time as last_processed_at for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
        """
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(last_processed_at=datetime.now(timezone.utc))
        )
        self._session.commit()

    def list_by_status(self, status: str | None) -> Sequence[FileRecord]:
        """Return all file records, optionally filtered to a specific status.

        Args:
            status: Pipeline status to filter on, or None to return all records.

        Returns:
            Sequence of FileRecord instances matching the filter.
        """
        if status is None:
            return self._session.execute(select(FileRecord)).scalars().all()
        return self._session.execute(select(FileRecord).where(FileRecord.status == status)).scalars().all()

    async def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        """Insert a new file record or reset it to 'pending' on conflict (sync session, async interface).

        Args:
            drive_file_id: Unique source identifier for the file.
            name: Display file name.
            mime_type: MIME type string of the file.
            drive_modified_at: Last-modified timestamp from the source.
        """
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
        """Synchronously patch raw-stage columns, updating only provided fields.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_raw_key: MinIO object key for the raw file, if changed.
            raw_source_version: Source version string, if changed.
            raw_checksum: SHA-256 hex digest of the raw file, if changed.
            raw_status: New raw pipeline status (e.g. 'synced'), if changed.
        """
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
        """Synchronously patch text-stage columns, updating only provided fields.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_text_key: MinIO object key for the extracted text, if changed.
            text_source_checksum: Checksum of the raw file this text was extracted from.
            text_checksum: Checksum of the extracted text content itself.
            text_status: New text pipeline status (e.g. 'ready_for_embedding').
            text_error: Error description to store, or None to clear a previous error.
        """
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
        if text_status == "embedding_queued":
            values["last_processed_at"] = datetime.now(timezone.utc)
        if values:
            self._session.execute(update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(**values))
            self._session.commit()

    def list_ready_for_embedding_sync(self) -> Sequence[FileRecord]:
        """Return all file records with text_status='ready_for_embedding'.

        Returns:
            Sequence of FileRecord instances waiting to be embedded.
        """
        return (
            self._session.execute(
                select(FileRecord).where(FileRecord.text_status == "ready_for_embedding")
            )
            .scalars()
            .all()
        )

    def batch_mark_embedding_queued_sync(self) -> list[dict]:
        """Atomically flip all ready_for_embedding (with text key) to embedding_queued in one query."""
        result = self._session.execute(
            text(
                """
                UPDATE file_records
                SET text_status = 'embedding_queued',
                    text_error = NULL,
                    last_processed_at = NOW()
                WHERE text_status = 'ready_for_embedding'
                  AND minio_text_key IS NOT NULL
                RETURNING drive_file_id, minio_text_key, minio_raw_key, mime_type, name
                """
            )
        )
        self._session.commit()
        return [dict(row) for row in result.mappings()]

    def batch_fail_missing_text_key_sync(self) -> int:
        """Mark ready_for_embedding files with no minio_text_key as failed (returns count)."""
        result = self._session.execute(
            text(
                """
                UPDATE file_records
                SET text_status = 'failed',
                    text_error = 'Missing minio_text_key for embedding handoff'
                WHERE text_status = 'ready_for_embedding'
                  AND minio_text_key IS NULL
                """
            )
        )
        self._session.commit()
        return result.rowcount

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
                  AND (last_processed_at IS NULL OR last_processed_at < :cutoff)
                """
            ),
            {"cutoff": cutoff},
        )
        self._session.commit()
        return result.rowcount

    def list_vision_pending_sync(self) -> Sequence[FileRecord]:
        """Return all file records with status='vision_pending'.

        Returns:
            Sequence of FileRecord instances awaiting vision OCR processing.
        """
        return (
            self._session.execute(
                select(FileRecord).where(FileRecord.status == "vision_pending")
            )
            .scalars()
            .all()
        )

    def update_chunk_count(self, drive_file_id: str, count: int) -> None:
        """Update the stored chunk count for a file after embedding.

        Args:
            drive_file_id: Unique source identifier for the file.
            count: Number of embedded chunks produced from this file.
        """
        self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(chunk_count=count)
        )
        self._session.commit()

    def update_text_key_sync(self, drive_file_id: str, minio_text_key: str) -> None:
        """Synchronously update the MinIO text object key for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_text_key: New MinIO object key for the extracted text.
        """
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(minio_text_key=minio_text_key)
        )
        self._session.commit()

    def update_raw_key_sync(self, drive_file_id: str, minio_raw_key: str) -> None:
        """Synchronously update the MinIO raw object key for a file record.

        Args:
            drive_file_id: Unique source identifier for the file.
            minio_raw_key: New MinIO object key for the raw file.
        """
        self._session.execute(
            update(FileRecord).where(FileRecord.drive_file_id == drive_file_id).values(minio_raw_key=minio_raw_key)
        )
        self._session.commit()

    async def get_page_token(self) -> str:
        """Retrieve the current sync page token (sync session, async interface).

        Returns:
            The stored sync token string, or an empty string for the first run.
        """
        state = self._session.execute(select(SyncState).where(SyncState.key == "drive_page_token")).scalar_one_or_none()
        if not state:
            state = SyncState(key="drive_page_token", value="")
            self._session.add(state)
            self._session.commit()
            self._session.refresh(state)
        return state.value

    async def update_page_token(self, token: str) -> None:
        """Upsert the sync page token in the sync_state table (sync session, async interface).

        Args:
            token: New page token returned by the source after a sync cycle.
        """
        stmt = _upsert_insert_for_session(self._session, SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        self._session.execute(stmt)
        self._session.commit()

    def delete_file_record_sync(self, drive_file_id: str) -> None:
        """Synchronously delete a single file record from the database.

        Args:
            drive_file_id: Unique source identifier of the file to delete.
        """
        self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        self._session.commit()

    async def delete_file_record(self, drive_file_id: str) -> None:
        """Delete a single file record (sync session, async interface).

        Args:
            drive_file_id: Unique source identifier of the file to delete.
        """
        self.delete_file_record_sync(drive_file_id)

    def delete_all_file_records_sync(self) -> None:
        """Synchronously delete all file records from the database."""
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
        """Synchronously insert or overwrite the extracted document record for a file.

        Args:
            drive_file_id: Unique source identifier linking this record to a file_records row.
            document_type: Optional document classification string.
            issuer: Optional issuer name from the document.
            issued_at: Optional document issuance date.
            total_amount: Optional monetary total extracted from the document.
            currency: Optional ISO-4217 currency code.
            parties: Optional list of parties named in the document.
            extras: Optional dict of additional extracted key-value fields.
        """
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
        """Synchronously fetch the extracted document record for a given file.

        Args:
            drive_file_id: Unique source identifier of the file.

        Returns:
            ExtractedDocument if it exists, or None if not yet extracted.
        """
        return self._session.execute(
            select(ExtractedDocument).where(ExtractedDocument.drive_file_id == drive_file_id)
        ).scalar_one_or_none()


async def init_db(database_url: str) -> None:
    """Create all ORM-defined tables and backfill any missing stage columns.

    Args:
        database_url: Async-compatible SQLAlchemy database URL.
    """
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
