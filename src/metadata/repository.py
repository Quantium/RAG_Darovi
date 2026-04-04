from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import DateTime, Integer, String, Text, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


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

    async def list_by_status(self, status: str) -> Sequence[FileRecord]:
        result = await self._session.execute(select(FileRecord).where(FileRecord.status == status))
        return result.scalars().all()

    async def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        stmt = sqlite_insert(FileRecord).values(
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
        stmt = sqlite_insert(SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        await self._session.execute(stmt)
        await self._session.commit()

    async def delete_file_record(self, drive_file_id: str) -> None:
        await self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        await self._session.commit()


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

    def get_file(self, drive_file_id: str) -> FileRecord | None:
        return self._session.execute(select(FileRecord).where(FileRecord.drive_file_id == drive_file_id)).scalar_one_or_none()

    def update_status(self, drive_file_id: str, status: str, error_message: str | None = None) -> None:
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(status=status, error_message=error_message)
        )
        self._session.commit()

    def update_last_processed_at(self, drive_file_id: str) -> None:
        self._session.execute(
            update(FileRecord)
            .where(FileRecord.drive_file_id == drive_file_id)
            .values(last_processed_at=datetime.now(timezone.utc))
        )
        self._session.commit()

    def list_by_status(self, status: str) -> Sequence[FileRecord]:
        return self._session.execute(select(FileRecord).where(FileRecord.status == status)).scalars().all()

    def upsert_file(
        self, drive_file_id: str, name: str, mime_type: str, drive_modified_at: datetime | None = None
    ) -> None:
        # SQLite dialect specific upsert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(FileRecord).values(
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

    def get_page_token(self) -> str:
        state = self._session.execute(select(SyncState).where(SyncState.key == "drive_page_token")).scalar_one_or_none()
        if not state:
            state = SyncState(key="drive_page_token", value="")
            self._session.add(state)
            self._session.commit()
            self._session.refresh(state)
        return state.value

    def update_page_token(self, token: str) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(SyncState).values(key="drive_page_token", value=token)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
        self._session.execute(stmt)
        self._session.commit()

    def delete_file_record(self, drive_file_id: str) -> None:
        self._session.execute(delete(FileRecord).where(FileRecord.drive_file_id == drive_file_id))
        self._session.commit()


async def init_db(database_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
