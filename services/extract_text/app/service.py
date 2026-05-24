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
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._storage = storage

    def run_once(self) -> dict[str, int]:
        if not self._repo.try_acquire_lock(self._settings.extract_text_lock_id):
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
                    text_key = f"{record.drive_file_id}.md"
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
            self._repo.release_lock(self._settings.extract_text_lock_id)

        logger.info("extract_text.run_once", scanned=scanned, updated=updated, failed=failed)
        return {"scanned": scanned, "updated": updated, "failed": failed}
