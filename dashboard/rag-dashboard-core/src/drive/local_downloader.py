from __future__ import annotations

import asyncio
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from config.settings import Settings
from src.storage.backend import StorageBackend

logger = structlog.get_logger()


class LocalFolderDownloader:
    """Downloader implementation that ingests files from a local folder."""

    def __init__(self, storage: StorageBackend, metadata_repo: Any, settings: Settings) -> None:
        self._storage = storage
        self._metadata_repo = metadata_repo
        self._settings = settings
        self._source_folder = Path(settings.local_source_folder).expanduser().resolve()

    async def full_sync(self) -> list[dict[str, Any]]:
        files = self._scan_files()
        await self._metadata_repo.update_page_token(self._snapshot_token(files))
        logger.info("local.full_sync.complete", count=len(files), folder=str(self._source_folder))
        return files

    async def incremental_sync(self) -> tuple[list[dict[str, Any]], list[str]]:
        files = self._scan_files()
        current_by_id = {file_meta["id"]: file_meta for file_meta in files}

        existing_records = self._metadata_repo.list_by_status(None)
        existing_ids = {record.drive_file_id for record in existing_records}
        deleted_ids = sorted(existing_ids - set(current_by_id))

        changed_files: list[dict[str, Any]] = []
        for file_id, file_meta in current_by_id.items():
            existing = next((record for record in existing_records if record.drive_file_id == file_id), None)
            if existing is None:
                changed_files.append(file_meta)
                continue

            current_modified = self._to_iso_z(existing.drive_modified_at) if existing.drive_modified_at else ""
            if current_modified != file_meta["modifiedTime"]:
                changed_files.append(file_meta)

        await self._metadata_repo.update_page_token(self._snapshot_token(files))
        logger.info("local.incremental_sync.complete", changed=len(changed_files), deleted=len(deleted_ids))
        return changed_files, deleted_ids

    async def download_file(self, file_meta: dict[str, Any]) -> str | None:
        file_id = file_meta["id"]
        name = file_meta["name"]
        mime_type = file_meta["mimeType"]
        modified_str = file_meta.get("modifiedTime", "")
        local_path = Path(file_meta.get("localPath") or (self._source_folder / file_id))

        existing = await self._metadata_repo.get_file(file_id)
        if existing and existing.drive_modified_at:
            current_modified = self._to_iso_z(existing.drive_modified_at)
            if current_modified == modified_str:
                logger.debug("local.download.skip_unchanged", file_id=file_id, name=name)
                return None

        content = await asyncio.to_thread(local_path.read_bytes)
        raw_key = file_id
        await asyncio.to_thread(self._storage.upload, self._settings.minio_bucket_raw, raw_key, content)

        drive_modified_at = datetime.fromisoformat(modified_str.replace("Z", "+00:00")) if modified_str else None
        await self._metadata_repo.upsert_file(
            drive_file_id=file_id,
            name=name,
            mime_type=mime_type,
            drive_modified_at=drive_modified_at,
        )
        await self._metadata_repo.update_status(file_id, "downloaded")
        return raw_key

    def _scan_files(self) -> list[dict[str, Any]]:
        if not self._settings.local_source_folder:
            raise RuntimeError("LOCAL_SOURCE_FOLDER is required when INGEST_SOURCE=local")
        if not self._source_folder.exists() or not self._source_folder.is_dir():
            raise RuntimeError(f"LOCAL_SOURCE_FOLDER does not exist or is not a directory: {self._source_folder}")

        files: list[dict[str, Any]] = []
        for path in sorted(p for p in self._source_folder.rglob("*") if p.is_file()):
            rel_path = path.relative_to(self._source_folder).as_posix()
            mime_type, _ = mimetypes.guess_type(path.name)
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
            files.append(
                {
                    "id": rel_path,
                    "name": path.name,
                    "mimeType": mime_type or "application/octet-stream",
                    "modifiedTime": modified_at,
                    "localPath": str(path),
                }
            )
        return files

    @staticmethod
    def _snapshot_token(files: list[dict[str, Any]]) -> str:
        return "|".join(f"{item['id']}:{item['modifiedTime']}" for item in files)

    @staticmethod
    def _to_iso_z(value: datetime | str) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        text = str(value)
        if text.endswith("+00:00"):
            return text.replace("+00:00", "Z")
        return text
