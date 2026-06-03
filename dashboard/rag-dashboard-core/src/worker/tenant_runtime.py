"""Tenant context for the Celery embedding pipeline.

The worker routes every file to its licitación's PostgreSQL schema and Milvus
collection. The context (slug / schema_name / collection) is read once from the
registry by the poll tasks, carried through the Celery chain inside the task
payload dict, and reconstructed by :func:`context_from_payload` in each task.

When the registry is missing or empty the pipeline falls back to the legacy
single-tenant layout (public schema, the global ``rag_documents`` collection, no
slug prefix), so a stack with no licitaciones behaves exactly as before
multi-tenancy.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from config.settings import Settings
from src.tenant.slug import pause_key

# Slug-less global key kept for backward compatibility: the dashboard's existing
# "pause vectorization" button sets this and it acts as a kill switch across every
# licitación. Per-licitación pausing additionally uses ``pause_key('vectorize', slug)``.
VECTORIZE_PAUSE_KEY = "rag:pause:vectorize"


@dataclass(frozen=True)
class TenantContext:
    """Resolved isolation target for one licitación in the embedding pipeline."""

    slug: str
    schema_name: str
    collection: str

    @classmethod
    def legacy(cls, settings: Settings) -> "TenantContext":
        """Pre-multitenancy layout: public schema, global collection, no slug."""
        return cls(slug="", schema_name="public", collection=settings.milvus_collection)

    def vectorize_pause_keys(self) -> tuple[str, ...]:
        """Pause keys that mute this licitación: the global key plus its per-slug key."""
        if self.slug:
            return (VECTORIZE_PAUSE_KEY, pause_key("vectorize", self.slug))
        return (VECTORIZE_PAUSE_KEY,)

    def payload(self) -> dict[str, str]:
        """Serialize the context into the Celery task payload dict."""
        return {"slug": self.slug, "schema_name": self.schema_name, "collection": self.collection}


def context_from_payload(payload: dict, settings: Settings) -> TenantContext:
    """Rebuild a TenantContext from a task payload, defaulting absent keys to the legacy layout.

    Payloads produced before multi-tenancy (and the legacy in-dashboard ingest chain,
    which is public-only) carry none of these keys, so they resolve to the public schema
    and the global collection — unchanged behavior.
    """
    legacy = TenantContext.legacy(settings)
    return TenantContext(
        slug=payload.get("slug") or "",
        schema_name=payload.get("schema_name") or legacy.schema_name,
        collection=payload.get("collection") or legacy.collection,
    )


def read_active_tenants(engine: Engine, settings: Settings) -> list[TenantContext]:
    """Return the active licitaciones from the registry, or the legacy tenant as fallback.

    Reads ``licitaciones`` through a base (public-default) engine. Falls back to a single
    legacy tenant when the table does not exist yet (pre-migration / pre-seed) or holds no
    active rows, so the poll never crashes on a fresh database.
    """
    with engine.begin() as conn:
        schema = "public" if conn.dialect.name == "postgresql" else None
        if not inspect(conn).has_table("licitaciones", schema=schema):
            return [TenantContext.legacy(settings)]
        rows = (
            conn.execute(
                text(
                    "SELECT slug, schema_name, milvus_collection "
                    "FROM licitaciones WHERE status = 'active' ORDER BY name"
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        return [TenantContext.legacy(settings)]
    return [
        TenantContext(
            slug=r["slug"], schema_name=r["schema_name"], collection=r["milvus_collection"]
        )
        for r in rows
    ]


def is_vectorize_paused(redis_client, tenant: TenantContext) -> bool:
    """True if vectorization is paused globally or for this specific licitación."""
    return any(redis_client.exists(key) for key in tenant.vectorize_pause_keys())
