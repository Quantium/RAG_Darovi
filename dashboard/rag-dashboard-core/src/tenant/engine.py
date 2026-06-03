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

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config.settings import Settings
from src.tenant.slug import validate_schema_name


def build_tenant_engine(settings: Settings, schema_name: str) -> Engine:
    """Build a sync engine scoped to ``schema_name`` (psycopg ``-csearch_path``)."""
    validate_schema_name(schema_name)
    url = settings.database_url_sync.get_secret_value()
    if url.startswith("sqlite"):
        return create_engine(url)
    return create_engine(url, connect_args={"options": f"-csearch_path={schema_name},public"})


def build_async_tenant_engine(settings: Settings, schema_name: str) -> AsyncEngine:
    """Build an async engine scoped to ``schema_name`` (asyncpg ``server_settings``)."""
    validate_schema_name(schema_name)
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite"):
        return create_async_engine(url)
    return create_async_engine(
        url, connect_args={"server_settings": {"search_path": f"{schema_name},public"}}
    )
