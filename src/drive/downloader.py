from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime
from typing import Any

import structlog
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from config.settings import Settings
from src.metadata.repository import MetadataRepository
from src.storage.backend import StorageBackend

logger = structlog.get_logger()


class DriveDownloader:
    def __init__(
        self,
        drive_service: Resource,
        storage: StorageBackend,
        metadata_repo: MetadataRepository,
        settings: Settings,
    ) -> None:
        self._drive_service = drive_service
        self._storage = storage
        self._metadata_repo = metadata_repo
        self._settings = settings

    async def full_sync(self) -> list[dict[str, Any]]:
        """Perform initial bootstrap scan of the configured folder."""
        logger.info("drive.full_sync.start", folder_id=self._settings.drive_folder_id)
        
        files = []
        page_token = None
        
        query = f"'{self._settings.drive_folder_id}' in parents"
        if not self._settings.drive_folder_id:
             query = "trashed = false"

        while True:
            response = (
                self._drive_service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                    pageToken=page_token,
                )
                .execute()
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Acquire and persist start page token for future incremental syncs
        token_resp = self._drive_service.changes().getStartPageToken().execute()
        start_token = token_resp.get("startPageToken")
        await self._metadata_repo.update_page_token(start_token)
        
        logger.info("drive.full_sync.complete", count=len(files), start_token=start_token)
        return files

    async def incremental_sync(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Detect changes since last sync."""
        token = await self._metadata_repo.get_page_token()
        if not token:
            logger.info("drive.incremental_sync.no_token_delegating_to_full")
            files = await self.full_sync()
            return files, []

        logger.info("drive.incremental_sync.start", token=token)
        
        changed_files = []
        deleted_ids = []
        
        page_token = token
        while True:
            response = (
                self._drive_service.changes()
                .list(
                    pageToken=page_token,
                    spaces="drive",
                    fields="nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, modifiedTime, trashed))",
                )
                .execute()
            )
            
            for change in response.get("changes", []):
                file_id = change.get("fileId")
                file_meta = change.get("file")
                
                if change.get("removed") or (file_meta and file_meta.get("trashed")):
                    deleted_ids.append(file_id)
                elif file_meta:
                    changed_files.append(file_meta)
            
            page_token = response.get("nextPageToken")
            if not page_token:
                new_token = response.get("newStartPageToken")
                if new_token:
                    await self._metadata_repo.update_page_token(new_token)
                break

        logger.info("drive.incremental_sync.complete", changed=len(changed_files), deleted=len(deleted_ids))
        return changed_files, deleted_ids

    async def download_file(self, file_meta: dict[str, Any]) -> str | None:
        """Download file and store in raw storage."""
        file_id = file_meta["id"]
        name = file_meta["name"]
        mime_type = file_meta["mimeType"]
        drive_modified_str = file_meta.get("modifiedTime")
        
        # Check if already processed and unchanged
        existing = await self._metadata_repo.get_file(file_id)
        if existing and existing.drive_modified_at:
             # Very basic comparison for now
             current_modified_str = ""
             if isinstance(existing.drive_modified_at, datetime):
                 current_modified_str = existing.drive_modified_at.isoformat().replace("+00:00", "Z")
             else:
                 current_modified_str = str(existing.drive_modified_at)
             
             if current_modified_str == drive_modified_str:
                 logger.debug("drive.download.skip_unchanged", file_id=file_id, name=name)
                 return None

        logger.info("drive.download.start", file_id=file_id, name=name)
        
        try:
            content = await self._download_with_retry(file_id, mime_type)
            
            # Upload to MinIO
            raw_key = f"{file_id}/{name}"
            await asyncio.to_thread(
                self._storage.upload, 
                self._settings.minio_bucket_raw, 
                raw_key, 
                content
            )
            
            # Update metadata
            drive_modified_at = None
            if drive_modified_str:
                # Handle 'Z' suffix for UTC
                drive_modified_at = datetime.fromisoformat(drive_modified_str.replace("Z", "+00:00"))

            await self._metadata_repo.upsert_file(
                drive_file_id=file_id,
                name=name,
                mime_type=mime_type,
                drive_modified_at=drive_modified_at
            )
            await self._metadata_repo.update_status(file_id, "downloaded")
            
            return raw_key
            
        except Exception as e:
            logger.error("drive.download.error", file_id=file_id, error=str(e))
            # Optional: update status to failed
            await self._metadata_repo.update_status(file_id, "failed", error_message=str(e))
            raise

    async def _download_with_retry(self, file_id: str, mime_type: str, max_retries: int = 3) -> bytes:
        retries = 0
        while True:
            try:
                if mime_type == "application/vnd.google-apps.document":
                    request = self._drive_service.files().export_media(fileId=file_id, mimeType="text/plain")
                elif mime_type == "application/vnd.google-apps.spreadsheet":
                    request = self._drive_service.files().export_media(fileId=file_id, mimeType="text/csv")
                else:
                    request = self._drive_service.files().get_media(fileId=file_id)

                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = await asyncio.to_thread(downloader.next_chunk)
                
                return fh.getvalue()
            except HttpError as e:
                if e.resp.status == 429 and retries < max_retries:
                    wait = 2 ** retries
                    logger.warning("drive.download.rate_limited", file_id=file_id, wait=wait)
                    await asyncio.sleep(wait)
                    retries += 1
                    continue
                raise
            except Exception:
                raise
