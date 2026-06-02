from __future__ import annotations

import hashlib

import structlog

from .db import MetadataRepository
from .extractors import extract_text, has_sentinels
from .settings import Settings
from .storage import MinIOStorage

logger = structlog.get_logger()


class ExtractTextService:
    def __init__(
        self,
        settings: Settings,
        repo: MetadataRepository,
        storage: MinIOStorage,
        text_key_prefix: str = "",
        manage_lock: bool = True,
    ) -> None:
        """Initialize the extraction service with its dependencies.

        Args:
            settings: Application settings controlling batch size and lock ID.
            repo: Metadata repository for reading candidates and updating statuses.
            storage: MinIO storage client for downloading raw files and uploading texts.
            text_key_prefix: Per-licitación MinIO key prefix for converted text (e.g. '<slug>/');
                empty for the legacy single-tenant key space.
            manage_lock: When False, the caller (TenantExtractService) holds the advisory lock for
                the whole run, so this instance neither acquires nor releases it.
        """
        self._settings = settings
        self._repo = repo
        self._storage = storage
        self._text_key_prefix = text_key_prefix
        self._manage_lock = manage_lock

    def run_once(self) -> dict[str, int]:
        """Process one batch of raw files needing text extraction.

        Acquires an advisory lock to prevent concurrent runs, extracts text from each
        candidate, uploads the result to MinIO, and updates the file record status.

        Returns:
            Dict with 'scanned', 'updated', and 'failed' counts for the batch.
        """
        if self._manage_lock and not self._repo.try_acquire_lock(self._settings.extract_text_lock_id):
            logger.info("extract_text.skipped", reason="another extraction run is active")
            return {"scanned": 0, "updated": 0, "failed": 0}

        scanned = 0
        updated = 0
        failed = 0
        self._storage.ensure_buckets()
        try:
            for record in self._repo.list_raw_changed_candidates(self._settings.extract_text_batch_size):
                scanned += 1
                self._repo.mark_text_processing(record.drive_file_id)
                try:
                    raw_bytes = self._storage.download_raw(record.minio_raw_key)
                    text = extract_text(raw_bytes, record.mime_type, record.name, self._settings)
                    text_bytes = text.encode("utf-8")
                    text_key = f"{self._text_key_prefix}{record.drive_file_id}.md"
                    self._storage.upload_text(text_key, text_bytes)
                    text_checksum = hashlib.sha256(text_bytes).hexdigest()
                    if has_sentinels(text):
                        self._repo.mark_text_vision_pending(
                            record.drive_file_id,
                            minio_text_key=text_key,
                            text_source_checksum=record.raw_checksum,
                            text_checksum=text_checksum,
                        )
                    else:
                        self._repo.mark_text_ready(
                            record.drive_file_id,
                            minio_text_key=text_key,
                            text_source_checksum=record.raw_checksum,
                            text_checksum=text_checksum,
                        )
                    updated += 1
                except Exception as exc:
                    self._repo.mark_text_failed(record.drive_file_id, str(exc))
                    failed += 1
        finally:
            if self._manage_lock:
                self._repo.release_lock(self._settings.extract_text_lock_id)

        logger.info("extract_text.run_once", scanned=scanned, updated=updated, failed=failed)
        return {"scanned": scanned, "updated": updated, "failed": failed}
