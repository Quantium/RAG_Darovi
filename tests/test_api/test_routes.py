"""Tests for src/api/routes.py — turns GREEN in Phase 7."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from uuid import uuid4

from src.api.app import create_app
from config.settings import Settings


@pytest.fixture
async def app_mocked(mock_milvus_client, mock_redis_client):
    app = create_app()
    # Mock dependencies in state to avoid real connections during tests
    app.state.settings = Settings()
    app.state.engine = AsyncMock()
    
    mock_retriever = AsyncMock()
    mock_retriever.retrieve.return_value = []
    app.state.retriever = mock_retriever
    
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "Mocked answer"
    mock_llm.chat_stream = AsyncMock()
    app.state.llm = mock_llm
    
    app.state.conversation_store = MagicMock()
    app.state.conversation_store.get_history.return_value = []
    
    return app


class TestAPIRoutes:
    @pytest.mark.integration
    async def test_chat_endpoint_returns_answer(self, app_mocked):
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            assert response.status_code == 200
            data = response.json()
            assert "answer" in data
            assert data["answer"] == "Mocked answer"

    @pytest.mark.integration
    async def test_chat_endpoint_includes_references(self, app_mocked):
        from src.rag.retriever import RetrievedChunk
        app_mocked.state.retriever.retrieve.return_value = [
            RetrievedChunk(text="ref text", source_file_id="f1", source_name="n1", section_title="s1", chunk_index=0, score=0.9)
        ]
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "sources" in data
            assert len(data["sources"]) == 1

    @pytest.mark.integration
    async def test_status_endpoint(self, app_mocked):
        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/status")
                assert response.status_code == 200
                assert response.json()["total_files"] == 0

    @pytest.mark.integration
    async def test_status_files_endpoint(self, app_mocked):
        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/status/files")
                assert response.status_code == 200
                assert isinstance(response.json(), list)

    @pytest.mark.integration
    async def test_generate_sql_endpoint(self, app_mocked):
        with patch("redis.Redis.from_url") as mock_redis:
            with patch("src.worker.tasks.run_sql_generation.delay") as mock_task:
                async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                    response = await client.post("/generate-sql", json={"description": "invoices"})
                    assert response.status_code == 200
                    assert "job_id" in response.json()

    @pytest.mark.integration
    async def test_generate_sql_poll(self, app_mocked):
        with patch("redis.Redis.from_url") as mock_redis:
            mock_client = mock_redis.return_value
            mock_client.hgetall.return_value = {b"status": b"pending"}
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/generate-sql/test-job-id")
                assert response.status_code == 200
                assert response.json()["status"] == "pending"

    @pytest.mark.integration
    async def test_chat_returns_conversation_id(self, app_mocked):
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "What is revenue?"})
            data = response.json()
            assert "conversation_id" in data
            assert len(data["conversation_id"]) > 0

    @pytest.mark.integration
    async def test_websocket_chat(self, app_mocked):
        from fastapi.testclient import TestClient
        
        # Setup streaming mock as a regular function returning an async generator
        async def mock_stream(*args, **kwargs):
            yield "token1"
            yield "token2"
        
        # Use a regular MagicMock for chat_stream so it returns the generator directly
        app_mocked.state.llm.chat_stream = MagicMock(side_effect=mock_stream)
        
        client = TestClient(app_mocked)
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "query", "query": "Hello", "conversation_id": "test-conv"})
            
            # Receive tokens
            msg1 = ws.receive_json()
            assert msg1["type"] == "token"
            
            msg2 = ws.receive_json()
            assert msg2["type"] == "token"
            
            # Receive done
            done = ws.receive_json()
            assert done["type"] == "done"


class TestAPIAuth:
    @pytest.fixture
    async def app_with_key(self, mock_milvus_client, mock_redis_client):
        with patch.dict("os.environ", {"API_KEY": "test-secret-key"}):
            app = create_app()
            app.state.settings = Settings()
            app.state.engine = AsyncMock()
            return app

    @pytest.mark.integration
    async def test_api_key_auth_rejects_invalid_key(self, app_with_key):
        async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
            response = await client.get("/status", headers={"X-API-Key": "wrong-key"})
            assert response.status_code == 401

    @pytest.mark.integration
    async def test_api_key_auth_allows_valid_key(self, app_with_key):
        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app_with_key), base_url="http://test") as client:
                response = await client.get("/status", headers={"X-API-Key": "test-secret-key"})
                assert response.status_code == 200

    @pytest.mark.integration
    async def test_api_key_auth_disabled_when_empty(self, app_mocked):
        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/status")
                assert response.status_code == 200
