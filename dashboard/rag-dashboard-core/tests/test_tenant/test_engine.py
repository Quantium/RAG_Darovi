"""Tests for per-licitación engine builders (src/tenant/engine.py)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from config.settings import Settings
from src.tenant.engine import build_async_tenant_engine, build_tenant_engine


def _settings() -> Settings:
    return Settings(
        database_url=SecretStr("sqlite+aiosqlite://"),
        database_url_sync=SecretStr("sqlite://"),
    )


class TestBuildTenantEngine:
    def test_sqlite_skips_search_path_and_connects(self):
        """On SQLite no search_path override is applied and the engine is usable."""
        engine = build_tenant_engine(_settings(), "lic_obra_norte")
        assert isinstance(engine, Engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
        engine.dispose()

    def test_postgres_pins_search_path_via_connect_args(self):
        """On PostgreSQL the schema is pinned through the libpq options connect arg."""
        s = Settings(database_url_sync=SecretStr("postgresql+psycopg2://u:p@h/db"))
        with patch("src.tenant.engine.create_engine") as mock_create:
            build_tenant_engine(s, "lic_obra_norte")
        mock_create.assert_called_once_with(
            "postgresql+psycopg2://u:p@h/db",
            connect_args={"options": "-csearch_path=lic_obra_norte,public"},
        )

    def test_rejects_unsafe_schema_name(self):
        with pytest.raises(ValueError):
            build_tenant_engine(_settings(), "lic_obra; DROP SCHEMA public")


class TestBuildAsyncTenantEngine:
    def test_sqlite_returns_async_engine(self):
        engine = build_async_tenant_engine(_settings(), "lic_obra_norte")
        assert isinstance(engine, AsyncEngine)

    def test_postgres_pins_search_path_via_connect_event(self):
        """Neon ignores asyncpg server_settings, so the schema is pinned with a SET search_path
        'connect' event on the direct (unpooled) endpoint (the '-pooler' host segment stripped)."""
        s = Settings(
            database_url=SecretStr("postgresql+asyncpg://u:p@ep-x-pooler.r.aws.neon.tech/db")
        )
        engine = build_async_tenant_engine(s, "lic_obra_norte")
        assert isinstance(engine, AsyncEngine)
        # direct (unpooled) endpoint — '-pooler' stripped so the SET search_path actually applies
        # (Neon ignores asyncpg server_settings; the connect-event SET is integration-verified)
        assert engine.url.host == "ep-x.r.aws.neon.tech"
