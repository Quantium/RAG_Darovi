"""Multi-tenancy helpers for ingest_raw: licitación registry reads and per-tenant
search_path engines. Per-licitación pause is enforced by registry status — only
``status='active'`` licitaciones are ingested, so a paused/archived one is skipped
without any Redis dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from .settings import Settings

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_SCHEMA_RE = re.compile(r"^(public|lic_[a-z0-9_]+)$")


def validate_slug(slug: str) -> str:
    """Return the slug unchanged if identifier-safe, else raise ValueError."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}")
    return slug


def validate_schema_name(schema_name: str) -> str:
    """Guard a schema name (public or lic_<slug>) before interpolating it into search_path."""
    if not _SCHEMA_RE.match(schema_name):
        raise ValueError(f"invalid schema name {schema_name!r}")
    return schema_name


def tenant_key(slug: str | None, key: str) -> str:
    """Prefix a MinIO object key with the licitación slug folder (no prefix when slug is empty)."""
    if not slug:
        return key
    return f"{validate_slug(slug)}/{key}"


@dataclass
class Licitacion:
    slug: str
    source_path: str
    schema_name: str
    status: str

    @property
    def key_prefix(self) -> str:
        """MinIO key prefix: empty for the legacy public tenant, '<slug>/' for new schemas."""
        return "" if self.schema_name == "public" else f"{self.slug}/"


# Used when the registry is missing/empty so the service still ingests the legacy corpus
# (public schema, no prefix, full root) exactly as before multi-tenancy.
LEGACY_LICITACION = Licitacion(slug="", source_path="", schema_name="public", status="active")


def read_active_licitaciones(engine: Engine) -> list[Licitacion]:
    """Return active licitaciones from the global registry (public.licitaciones).

    Returns an empty list if the registry table does not exist yet (e.g. before the
    0006 migration / dashboard startup seed has run).
    """
    with engine.begin() as conn:
        if "licitaciones" not in inspect(conn).get_table_names(schema="public"):
            return []
        rows = (
            conn.execute(
                text(
                    "SELECT slug, COALESCE(source_path, '') AS source_path, schema_name, status "
                    "FROM public.licitaciones WHERE status = 'active' ORDER BY name"
                )
            )
            .mappings()
            .all()
        )
    return [
        Licitacion(
            slug=r["slug"],
            source_path=r["source_path"],
            schema_name=r["schema_name"],
            status=r["status"],
        )
        for r in rows
    ]


def _direct_url(url: str) -> str:
    """Return the Neon *direct* (unpooled) URL for a search_path-pinned tenant engine.

    Neon's pooler (PgBouncer) rejects the ``search_path`` libpq startup parameter
    ("unsupported startup parameter in options"), so any engine that pins search_path
    at connect time must target the direct endpoint — the pooled host minus its
    ``-pooler`` segment. No-op for non-pooled URLs (e.g. sqlite in tests), so it is
    always safe to apply.
    """
    return url.replace("-pooler.", ".", 1)


def build_tenant_engine(settings: Settings, schema_name: str) -> Engine:
    """Build a sync engine whose connections resolve unqualified tables in the licitación schema.

    The search_path is set via the libpq ``options`` connect arg, so every bare-table query in
    the existing raw-SQL repository transparently targets the tenant schema. The Neon direct
    (unpooled) endpoint is required because the pooler rejects the search_path startup param.
    """
    validate_schema_name(schema_name)
    url = _direct_url(settings.database_url_sync.get_secret_value())
    return create_engine(url, connect_args={"options": f"-csearch_path={schema_name},public"})
