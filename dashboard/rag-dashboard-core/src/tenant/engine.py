"""Per-licitación SQLAlchemy engines whose connections resolve unqualified tables
in the tenant schema.

The licitación ``search_path`` is pinned at the connection level (libpq ``options``
for the sync psycopg driver, asyncpg ``server_settings`` for the async driver) rather
than via ``SET LOCAL``. Connection-level pinning survives the repeated ``COMMIT`` calls
the Celery embedding pipeline issues, whereas ``SET LOCAL`` would reset on the first
commit. On SQLite (the unit-test database) there is a single schema, so the override is
skipped and a plain engine is returned.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config.settings import Settings
from src.tenant.slug import validate_schema_name


def _direct_url(url: str) -> str:
    """Return the Neon *direct* (unpooled) URL for a search_path-pinned tenant engine.

    Neon's pooler (PgBouncer) rejects the ``search_path`` startup parameter (libpq ``options``
    for psycopg, ``server_settings`` for asyncpg), so every engine that pins search_path at
    connect time must target the direct endpoint — the pooled host minus its ``-pooler``
    segment. No-op for non-pooled URLs (e.g. sqlite in tests), so it is always safe to apply.
    """
    return url.replace("-pooler.", ".", 1)


def build_tenant_engine(settings: Settings, schema_name: str) -> Engine:
    """Build a sync engine scoped to ``schema_name`` (psycopg ``-csearch_path``)."""
    validate_schema_name(schema_name)
    url = settings.database_url_sync.get_secret_value()
    if url.startswith("sqlite"):
        return create_engine(url)
    return create_engine(
        _direct_url(url), connect_args={"options": f"-csearch_path={schema_name},public"}
    )


def build_async_tenant_engine(settings: Settings, schema_name: str) -> AsyncEngine:
    """Build an async engine scoped to ``schema_name`` via a ``SET search_path`` connect hook.

    Neon **silently ignores** asyncpg ``server_settings={'search_path': ...}`` (a startup-packet
    GUC) — connections fall back to the default ``"$user", public``, so every per-tenant async
    write (embedding/vision write-back, dashboard resets) leaked into ``public``. An explicit
    ``SET search_path`` on each new DBAPI connection works (verified), so the search_path is
    pinned with a "connect" event listener instead. Connection-level, so it survives the
    repeated COMMITs of the embedding write-back. ``schema_name`` is allow-listed by
    ``validate_schema_name`` above, so it is safe to interpolate. SQLite (unit tests) is skipped.
    """
    validate_schema_name(schema_name)
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite"):
        return create_async_engine(url)
    engine = create_async_engine(_direct_url(url))

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {schema_name}, public")
        finally:
            cursor.close()

    return engine
