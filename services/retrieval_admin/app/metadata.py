from __future__ import annotations

from dataclasses import dataclass

from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import Settings


@dataclass
class FileStatusRow:
    drive_file_id: str
    name: str
    mime_type: str
    status: str
    error_message: str | None
    chunk_count: int
    last_processed_at: str | None
    minio_text_key: str | None


class MetadataService:
    def __init__(self, settings: Settings) -> None:
        self._engine = create_async_engine(settings.database_url.get_secret_value())
        self._session_factory = async_sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)
        self._minio = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._text_bucket = settings.minio_bucket_text

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_status_counts(self) -> dict[str, int]:
        query = text(
            """
            SELECT
                COUNT(*) AS total_files,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'downloaded') AS downloaded,
                COUNT(*) FILTER (WHERE status = 'converted') AS converted,
                COUNT(*) FILTER (WHERE status = 'embedded') AS embedded,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE status = 'vision_pending') AS vision_pending,
                COUNT(*) FILTER (WHERE status = 'vision_processing') AS vision_processing,
                COUNT(*) FILTER (WHERE status = 'vision_failed') AS vision_failed
            FROM file_records
            """
        )
        async with self._session_factory() as session:
            row = (await session.execute(query)).mappings().first()
            if row is None:
                return {
                    "total_files": 0,
                    "pending": 0,
                    "downloaded": 0,
                    "converted": 0,
                    "embedded": 0,
                    "failed": 0,
                    "vision_pending": 0,
                    "vision_processing": 0,
                    "vision_failed": 0,
                }
            return {key: int(row[key] or 0) for key in row.keys()}

    async def list_files(self) -> list[FileStatusRow]:
        query = text(
            """
            SELECT
                drive_file_id,
                name,
                mime_type,
                status,
                error_message,
                chunk_count,
                CAST(last_processed_at AS TEXT) AS last_processed_at,
                minio_text_key
            FROM file_records
            ORDER BY drive_file_id
            """
        )
        async with self._session_factory() as session:
            rows = (await session.execute(query)).mappings().all()
        return [FileStatusRow(**row) for row in rows]

    async def list_raw_data(self, max_chars: int = 6000) -> list[dict[str, str | None]]:
        files = await self.list_files()
        result: list[dict[str, str | None]] = []
        for file_row in files:
            extracted_text: str | None = None
            if file_row.minio_text_key:
                try:
                    obj = self._minio.get_object(self._text_bucket, file_row.minio_text_key)
                    try:
                        text_data = obj.read().decode("utf-8", errors="replace").strip()
                        extracted_text = text_data[:max_chars]
                    finally:
                        obj.close()
                        obj.release_conn()
                except Exception:
                    extracted_text = None
            result.append(
                {
                    "drive_file_id": file_row.drive_file_id,
                    "name": file_row.name,
                    "mime_type": file_row.mime_type,
                    "status": file_row.status,
                    "last_processed_at": file_row.last_processed_at,
                    "extracted_text": extracted_text,
                }
            )
        return result

    def raw_text_available(self, key: str | None) -> tuple[bool, str | None]:
        if not key:
            return False, "No extracted text key recorded."
        try:
            self._minio.stat_object(self._text_bucket, key)
            return True, None
        except Exception:
            return False, "Extracted text object not found in storage."
