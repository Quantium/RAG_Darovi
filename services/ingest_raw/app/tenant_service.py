"""Tenant-aware ingestion: runs the per-licitación IngestRawService for every active
licitación, each scoped to its source subfolder, PostgreSQL schema, and MinIO key prefix.

Exposes the same ``run_once()`` interface as IngestRawService so the cron loop and HTTP
trigger wiring are unchanged.
"""

from __future__ import annotations

import structlog
from sqlalchemy import create_engine

from .db import MetadataRepository
from .service import IngestRawService
from .settings import Settings
from .sources import LocalSourceAdapter
from .storage import MinIOStorage
from .tenant import LEGACY_LICITACION, Licitacion, build_tenant_engine, read_active_licitaciones

logger = structlog.get_logger()


class TenantIngestService:
    def __init__(self, settings: Settings) -> None:
        """Initialize with settings and a base (public) engine used to read the registry."""
        self._settings = settings
        self._base_engine = create_engine(settings.database_url_sync.get_secret_value())

    def run_once(self) -> dict[str, int]:
        """Ingest every active licitación in isolation; one failure does not abort the others."""
        licitaciones = read_active_licitaciones(self._base_engine) or [LEGACY_LICITACION]
        # Subfolders owned by other licitaciones — carved out of any licitación whose root
        # would otherwise also walk them (notably the public/root tenant).
        owned_subpaths = {lic.source_path for lic in licitaciones if lic.source_path}
        totals = {"scanned": 0, "updated": 0, "skipped": 0, "licitaciones": 0, "errors": 0}
        for lic in licitaciones:
            try:
                result = self._run_one(lic, exclude_prefixes=owned_subpaths - {lic.source_path})
                totals["scanned"] += result["scanned"]
                totals["updated"] += result["updated"]
                totals["skipped"] += result["skipped"]
                totals["licitaciones"] += 1
            except Exception as exc:  # isolate per-licitación failures
                totals["errors"] += 1
                logger.error("ingest_raw.tenant.failed", slug=lic.slug, error=str(exc))
        logger.info("ingest_raw.tenant.run_once", **totals)
        return totals

    def _run_one(self, lic: Licitacion, exclude_prefixes: set[str]) -> dict[str, int]:
        engine = build_tenant_engine(self._settings, lic.schema_name)
        try:
            repo = MetadataRepository(engine)
            source = LocalSourceAdapter(
                self._settings, sub_path=lic.source_path, exclude_prefixes=exclude_prefixes
            )
            storage = MinIOStorage(self._settings)
            service = IngestRawService(
                settings=self._settings,
                repo=repo,
                source=source,
                storage=storage,
                key_prefix=lic.key_prefix,
            )
            return service.run_once()
        finally:
            engine.dispose()
