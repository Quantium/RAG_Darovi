"""Tests for src/tenant/provisioning.py guards (real DDL is covered by the throwaway-PG run)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from src.tenant.provisioning import TENANT_TABLES, provision_tenant_schema


class TestProvisionTenantSchema:
    async def test_noop_on_sqlite(self, tmp_path):
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
        async with engine.begin() as conn:
            await provision_tenant_schema(conn, "lic_obra_norte")  # no-op on sqlite, must not raise
        await engine.dispose()

    async def test_rejects_public(self, tmp_path):
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p2.db'}")
        async with engine.begin() as conn:
            with pytest.raises(ValueError):
                await provision_tenant_schema(conn, "public")
        await engine.dispose()

    async def test_rejects_non_tenant_schema(self, tmp_path):
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p3.db'}")
        async with engine.begin() as conn:
            with pytest.raises(ValueError):
                await provision_tenant_schema(conn, "random_schema")
        await engine.dispose()

    def test_tenant_tables_set(self):
        assert set(TENANT_TABLES) == {
            "file_records",
            "extracted_documents",
            "sync_state",
            "chat_interactions",
        }
