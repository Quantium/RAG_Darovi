"""Route-level tests for the licitaciones CRUD API (sqlite-backed app, Milvus stubbed)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

import src.tenant.service as service_mod
from config.settings import Settings
from src.api.app import create_app
from src.metadata.repository import Base


@pytest.fixture
async def client(tmp_path, monkeypatch):
    # Don't touch Milvus during provisioning; schema DDL is a no-op on sqlite.
    monkeypatch.setattr(service_mod, "create_tenant_collection", lambda settings, name: None)

    settings = Settings(
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}"),
        api_key=SecretStr(""),
    )
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    app.state.settings = settings
    app.state.engine = engine
    app.state.redis_cache = MagicMock(scan_iter=MagicMock(return_value=iter([])))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()


class TestLicitacionesRoutes:
    async def test_create_list_archive_flow(self, client):
        r = await client.post("/licitaciones", json={"name": "Obra Norte", "source_path": "obra_norte"})
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["slug"] == "obra_norte"
        assert data["schema_name"] == "lic_obra_norte"
        assert data["milvus_collection"] == "rag_obra_norte"
        assert data["status"] == "active"
        lic_id = data["id"]

        r = await client.get("/licitaciones")
        assert r.status_code == 200
        assert any(x["id"] == lic_id for x in r.json())

        # duplicate name -> 409
        r = await client.post("/licitaciones", json={"name": "Obra Norte"})
        assert r.status_code == 409

        # archive requires the confirm header
        r = await client.request("DELETE", f"/licitaciones/{lic_id}")
        assert r.status_code == 400
        r = await client.request("DELETE", f"/licitaciones/{lic_id}", headers={"X-Dashboard-Confirm": "yes"})
        assert r.status_code == 200
        assert r.json()["status"] == "archived"

        # archived hidden from the default list
        r = await client.get("/licitaciones")
        assert all(x["id"] != lic_id for x in r.json())

    async def test_invalid_name_returns_400(self, client):
        r = await client.post("/licitaciones", json={"name": "!!!"})
        assert r.status_code == 400

    async def test_pause_resume(self, client):
        r = await client.post("/licitaciones", json={"name": "Obra Sur"})
        lic_id = r.json()["id"]
        r = await client.post(f"/licitaciones/{lic_id}/pause")
        assert r.status_code == 200 and r.json()["status"] == "paused"
        r = await client.post(f"/licitaciones/{lic_id}/resume")
        assert r.status_code == 200 and r.json()["status"] == "active"

    async def test_edit_rename_preserves_slug(self, client):
        r = await client.post("/licitaciones", json={"name": "Obra Centro"})
        lic_id = r.json()["id"]
        r = await client.patch(f"/licitaciones/{lic_id}", json={"name": "Obra Centro 2"})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Obra Centro 2"
        assert body["slug"] == "obra_centro"

    async def test_pause_unknown_404(self, client):
        r = await client.post("/licitaciones/does-not-exist/pause")
        assert r.status_code == 404
