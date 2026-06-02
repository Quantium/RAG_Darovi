"""Tenant-scoped database sessions.

Each licitación owns a PostgreSQL schema. We switch tenant by pinning the
connection ``search_path`` to ``<schema>, public`` with ``SET LOCAL`` inside a
single transaction, so it auto-resets when the transaction ends (pool-safe) and
every bare table reference — ORM and raw ``text()`` SQL alike — resolves inside
the tenant schema without rewriting any queries.

On non-PostgreSQL backends (the aiosqlite unit-test database) there is a single
schema, so the ``SET`` is skipped and the session is yielded as-is.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from src.tenant.slug import validate_schema_name


def _set_search_path_sql(schema_name: str) -> str:
    """Build the ``SET LOCAL search_path`` statement for a validated schema name.

    The schema name is validated against a strict allowlist because identifiers
    cannot be passed as bound parameters.
    """
    safe = validate_schema_name(schema_name)
    return f"SET LOCAL search_path TO {safe}, public"


@asynccontextmanager
async def tenant_session(engine: AsyncEngine, schema_name: str) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession scoped to the given licitación schema (one transaction)."""
    async with AsyncSession(engine) as session:
        async with session.begin():
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                await session.execute(text(_set_search_path_sql(schema_name)))
            yield session


@contextmanager
def tenant_session_sync(engine: Engine, schema_name: str) -> Iterator[Session]:
    """Sync counterpart of :func:`tenant_session` for Celery tasks and services."""
    with Session(engine) as session:
        with session.begin():
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                session.execute(text(_set_search_path_sql(schema_name)))
            yield session
