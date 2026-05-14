from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, delete, select, update
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
    drive_modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    minio_raw_key: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_text_key: Mapped[str | None] = mapped_column(String, nullable=True)


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
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


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
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
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
            },
        )
        await self._session.execute(stmt)
        await self._session.commit()

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
            },
        )
        self._session.execute(stmt)
        self._session.commit()

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
    await engine.dispose()
