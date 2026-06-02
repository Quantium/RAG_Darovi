"""Tenant-aware text extraction: holds the global advisory lock once, then runs the
per-licitación ExtractTextService for every active licitación, each scoped to its
PostgreSQL schema and MinIO text-key prefix.

The advisory lock is acquired a single time for the whole run (on a base/public engine);
the per-licitación services run with manage_lock=False so they do not fight over it.
Exposes the same ``run_once()`` interface as ExtractTextService.
"""

from __future__ import annotations

import structlog
from sqlalchemy import create_engine

from .db import MetadataRepository
from .service import ExtractTextService
from .settings import Settings
from .storage import MinIOStorage
from .tenant import LEGACY_LICITACION, Licitacion, build_tenant_engine, read_active_licitaciones

logger = structlog.get_logger()


class TenantExtractService:
    def __init__(self, settings: Settings) -> None:
        """Initialize with settings and a base (public) engine used for the lock + registry."""
        self._settings = settings
        self._base_engine = create_engine(settings.database_url_sync.get_secret_value())

    def run_once(self) -> dict[str, int]:
        """Extract text for every active licitación under a single global advisory lock."""
        base_repo = MetadataRepository(self._base_engine)
        if not base_repo.try_acquire_lock(self._settings.extract_text_lock_id):
            logger.info("extract_text.tenant.skipped", reason="another extraction run is active")
            return {"scanned": 0, "updated": 0, "failed": 0, "licitaciones": 0, "errors": 0}

        totals = {"scanned": 0, "updated": 0, "failed": 0, "licitaciones": 0, "errors": 0}
        try:
            licitaciones = read_active_licitaciones(self._base_engine) or [LEGACY_LICITACION]
            storage = MinIOStorage(self._settings)
            for lic in licitaciones:
                try:
                    result = self._run_one(lic, storage)
                    totals["scanned"] += result["scanned"]
                    totals["updated"] += result["updated"]
                    totals["failed"] += result["failed"]
                    totals["licitaciones"] += 1
                except Exception as exc:  # isolate per-licitación failures
                    totals["errors"] += 1
                    logger.error("extract_text.tenant.failed", slug=lic.slug, error=str(exc))
        finally:
            base_repo.release_lock(self._settings.extract_text_lock_id)

        logger.info("extract_text.tenant.run_once", **totals)
        return totals

    def _run_one(self, lic: Licitacion, storage: MinIOStorage) -> dict[str, int]:
        engine = build_tenant_engine(self._settings, lic.schema_name)
        try:
            repo = MetadataRepository(engine)
            service = ExtractTextService(
                settings=self._settings,
                repo=repo,
                storage=storage,
                text_key_prefix=lic.key_prefix,
                manage_lock=False,
            )
            return service.run_once()
        finally:
            engine.dispose()
