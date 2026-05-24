from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import structlog

from .db import MetadataRepository
from .settings import Settings
from .sources import SourceFile, SourceAdapter
from .storage import MinIOStorage

logger = structlog.get_logger()


class IngestRawService:
    def __init__(
        self,
        settings: Settings,
        repo: MetadataRepository,
        source: SourceAdapter,
        storage: MinIOStorage,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._source = source
        self._storage = storage

    def run_once(self) -> dict[str, int]:
        self._storage.ensure_bucket()
        scanned = 0
        updated = 0
        skipped = 0
        page_num = 0
        for page in self._source.iter_pages(self._settings.ingest_raw_page_size):
            page_num += 1
            for source_file in page:
                scanned += 1
                if self._is_unchanged(source_file):
                    skipped += 1
                    continue
                content = self._source.download_file(source_file)
                checksum = hashlib.sha256(content).hexdigest()
                raw_key = f"{source_file.file_id}/{source_file.name}"
                self._repo.upsert_file(
                    drive_file_id=source_file.file_id,
                    name=source_file.name,
                    mime_type=source_file.mime_type,
                    drive_modified_at=_to_datetime(source_file.source_version),
                )
                self._storage.upload_raw(raw_key, content)
                self._repo.update_raw_stage(
                    source_file.file_id,
                    minio_raw_key=raw_key,
                    raw_source_version=source_file.source_version,
                    raw_checksum=checksum,
                )
                updated += 1
            logger.info("ingest_raw.run_once.page", page=page_num, scanned=scanned, updated=updated, skipped=skipped)

        logger.info("ingest_raw.run_once", scanned=scanned, updated=updated, skipped=skipped)
        return {"scanned": scanned, "updated": updated, "skipped": skipped}

    def _is_unchanged(self, source_file: SourceFile) -> bool:
        record = self._repo.get_file(source_file.file_id)
        if record is None:
            return False
        return record.raw_status == "synced" and record.raw_source_version == source_file.source_version


def _to_datetime(source_version: str) -> datetime | None:
    try:
        if source_version.endswith("Z"):
            return datetime.fromisoformat(source_version.replace("Z", "+00:00"))
    except Exception:  # pragma: no cover - defensive parse
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
