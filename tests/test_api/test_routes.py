"""Tests for src/api/routes.py — turns GREEN in Phase 7."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from src.api.app import create_app


class TestAPIRoutes:
    @pytest.fixture
    def app(self):
        return create_app()

    @pytest.mark.integration
    async def test_chat_endpoint_returns_answer(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            assert response.status_code == 200
            data = response.json()
            assert "answer" in data

    @pytest.mark.integration
    async def test_chat_endpoint_includes_references(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "sources" in data

    @pytest.mark.integration
    async def test_status_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status")
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_status_files_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status/files")
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_generate_sql_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/generate-sql", json={"description": "invoices"})
            assert response.status_code == 200
            assert "job_id" in response.json()

    @pytest.mark.integration
    async def test_generate_sql_poll(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/generate-sql/test-job-id")
            assert response.status_code in (200, 404)

    @pytest.mark.integration
    async def test_chat_returns_conversation_id(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "conversation_id" in data
            assert len(data["conversation_id"]) > 0

    @pytest.mark.integration
    async def test_websocket_chat(self, app):
        from httpx_ws import aconnect_ws
        async with aconnect_ws("ws://test/ws/chat", app) as ws:
            await ws.send_json({"type": "query", "query": "Hello", "conversation_id": "test-conv"})
            msg = await ws.receive_json()
            assert msg["type"] in ("token", "done", "error")


class TestAPIAuth:
    """Tests for API key authentication — turns GREEN in Phase 7."""

    @pytest.fixture
    def app_with_key(self):
        """Create app with API_KEY configured."""
        import os
        os.environ["API_KEY"] = "test-secret-key"
        app = create_app()
        yield app
        del os.environ["API_KEY"]

    @pytest.mark.integration
    async def test_api_key_auth_rejects_invalid_key(self, app_with_key):
        async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
            response = await client.get("/status", headers={"X-API-Key": "wrong-key"})
            assert response.status_code == 401

    @pytest.mark.integration
    async def test_api_key_auth_allows_valid_key(self, app_with_key):
        async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
            response = await client.get("/status", headers={"X-API-Key": "test-secret-key"})
            assert response.status_code == 200

    @pytest.mark.integration
    async def test_api_key_auth_disabled_when_empty(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status")
            assert response.status_code == 200
