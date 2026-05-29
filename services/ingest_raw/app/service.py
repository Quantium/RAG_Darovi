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
        """Initialize the ingestion service with its dependencies.

        Args:
            settings: Application settings controlling page size and other parameters.
            repo: Metadata repository for upserting and updating file records.
            source: Source adapter that provides file listings and downloads.
            storage: MinIO storage client for uploading raw files.
        """
        self._settings = settings
        self._repo = repo
        self._source = source
        self._storage = storage

    def run_once(self) -> dict[str, int]:
        """Scan the source for changed files and upload any new or updated ones to MinIO.

        Skips files whose source version matches the already-synced version in the database.

        Returns:
            Dict with 'scanned', 'updated', and 'skipped' counts for the run.
        """
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
        """Return True if the file is already synced and its source version has not changed.

        Args:
            source_file: Source file metadata to compare against the stored record.

        Returns:
            True if the file is up-to-date in the database, False if it needs to be re-ingested.
        """
        record = self._repo.get_file(source_file.file_id)
        if record is None:
            return False
        return record.raw_status == "synced" and record.raw_source_version == source_file.source_version


def _to_datetime(source_version: str) -> datetime | None:
    """Parse an ISO-8601 source version string into a timezone-aware datetime.

    Falls back to the current UTC time if parsing fails.

    Args:
        source_version: Source version string, typically an ISO-8601 timestamp ending in 'Z'.

    Returns:
        Parsed UTC datetime, or the current UTC time if the string cannot be parsed.
    """
    try:
        if source_version.endswith("Z"):
            return datetime.fromisoformat(source_version.replace("Z", "+00:00"))
    except Exception:  # pragma: no cover - defensive parse
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
