"""Tests for src/tenant/session.py."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.metadata.repository import Base, Licitacion
from src.tenant.session import _set_search_path_sql, tenant_session


class TestSetSearchPathSql:
    def test_builds_statement(self) -> None:
        assert _set_search_path_sql("lic_obra_norte") == "SET LOCAL search_path TO lic_obra_norte, public"
        assert _set_search_path_sql("public") == "SET LOCAL search_path TO public, public"

    def test_rejects_bad_schema(self) -> None:
        with pytest.raises(ValueError):
            _set_search_path_sql("lic_obra; DROP SCHEMA public")


class TestTenantSessionSqlite:
    async def test_yields_working_session_and_commits(self, tmp_path) -> None:
        # File-backed sqlite so the row persists across the two connections below.
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # On sqlite the SET search_path is skipped; the session must still work and commit on exit.
        async with tenant_session(engine, "public") as session:
            session.add(
                Licitacion(
                    id="t1",
                    name="Tenant One",
                    slug="tenant_one",
                    schema_name="lic_tenant_one",
                    milvus_collection="rag_tenant_one",
                    status="active",
                )
            )

        async with AsyncSession(engine) as session:
            got = await session.get(Licitacion, "t1")
            assert got is not None
            assert got.slug == "tenant_one"

        await engine.dispose()

    async def test_rolls_back_on_error(self, tmp_path) -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant_rb.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        with pytest.raises(RuntimeError):
            async with tenant_session(engine, "public") as session:
                session.add(
                    Licitacion(
                        id="rb",
                        name="Rollback",
                        slug="rollback",
                        schema_name="lic_rollback",
                        milvus_collection="rag_rollback",
                        status="active",
                    )
                )
                raise RuntimeError("boom")

        async with AsyncSession(engine) as session:
            assert await session.get(Licitacion, "rb") is None

        await engine.dispose()
