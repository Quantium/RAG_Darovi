"""Tests for src/api/routes.py — turns GREEN in Phase 7."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from config.settings import Settings
from src.api.app import create_app


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
            RetrievedChunk(
                text="ref text", source_file_id="f1", source_name="n1", section_title="s1", chunk_index=0, score=0.9
            )
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
    async def test_status_files_endpoint_reports_raw_text_availability(self, app_mocked):
        available_record = MagicMock()
        available_record.drive_file_id = "file-1"
        available_record.name = "Invoice-April.pdf"
        available_record.mime_type = "application/pdf"
        available_record.status = "embedded"
        available_record.error_message = None
        available_record.chunk_count = 8
        available_record.last_processed_at = datetime.now(timezone.utc)
        available_record.minio_text_key = "file-1.txt"

        missing_record = MagicMock()
        missing_record.drive_file_id = "file-2"
        missing_record.name = "Contract-Draft.docx"
        missing_record.mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        missing_record.status = "embedded"
        missing_record.error_message = None
        missing_record.chunk_count = 5
        missing_record.last_processed_at = datetime.now(timezone.utc)
        missing_record.minio_text_key = "file-2.txt"

        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[available_record, missing_record])
            with patch("src.api.routes.MinIOStorage") as mock_storage_cls:
                mock_storage = mock_storage_cls.return_value
                mock_storage.exists.side_effect = [True, False]
                async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                    response = await client.get("/status/files")

        assert response.status_code == 200
        payload = response.json()
        assert payload[0]["raw_text_available"] is True
        assert payload[0]["raw_text_missing_reason"] is None
        assert payload[1]["raw_text_available"] is False
        assert payload[1]["raw_text_missing_reason"] == "Extracted text object not found in storage."

    @pytest.mark.integration
    async def test_status_raw_data_endpoint_returns_extracted_text(self, app_mocked):
        record = MagicMock()
        record.drive_file_id = "file-1"
        record.name = "Invoice-April.pdf"
        record.mime_type = "application/pdf"
        record.status = "embedded"
        record.last_processed_at = datetime.now(timezone.utc)
        record.minio_text_key = "file-1.txt"

        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_by_status = AsyncMock(return_value=[record])
            with patch("src.api.routes.MinIOStorage") as mock_storage_cls:
                mock_storage = mock_storage_cls.return_value
                mock_storage.download.return_value = b"Extracted invoice content"
                async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                    response = await client.get("/status/raw-data")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["name"] == "Invoice-April.pdf"
        assert payload[0]["extracted_text"] == "Extracted invoice content"

    @pytest.mark.integration
    async def test_open_file_redirects_to_google_drive_in_drive_mode(self, app_mocked):
        app_mocked.state.settings = Settings(ingest_source="drive")
        record = MagicMock()
        record.drive_file_id = "file-1"
        record.name = "Invoice-April.pdf"
        record.mime_type = "application/pdf"
        record.minio_raw_key = "file-1/Invoice-April.pdf"

        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_file = AsyncMock(return_value=record)
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/files/file-1/open", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "https://drive.google.com/open?id=file-1"

    @pytest.mark.integration
    async def test_open_file_streams_raw_file_in_local_mode(self, app_mocked):
        app_mocked.state.settings = Settings(ingest_source="local")
        record = MagicMock()
        record.drive_file_id = "file-1"
        record.name = "report.txt"
        record.mime_type = "text/plain"
        record.minio_raw_key = "file-1/report.txt"

        with patch("src.metadata.repository.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_file = AsyncMock(return_value=record)
            with patch("src.api.routes.MinIOStorage") as mock_storage_cls:
                mock_storage = mock_storage_cls.return_value
                mock_storage.download.return_value = b"hello world"
                async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                    response = await client.get("/files/file-1/open")

        assert response.status_code == 200
        assert response.text == "hello world"
        assert response.headers["content-type"].startswith("text/plain")

    @pytest.mark.integration
    async def test_generate_sql_endpoint(self, app_mocked):
        with patch("redis.Redis.from_url"):
            with patch("src.worker.tasks.run_sql_generation.delay"):
                async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                    response = await client.post("/generate-sql", json={"description": "invoices"})
                    assert response.status_code == 200
                    assert "job_id" in response.json()

    @pytest.mark.integration
    async def test_ingest_endpoint_dispatches_job(self, app_mocked):
        with patch("src.worker.tasks.run_incremental_sync.delay") as mock_delay:
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.post("/ingest")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        mock_delay.assert_called_once()

    @pytest.mark.integration
    async def test_restart_ingest_endpoint_dispatches_job(self, app_mocked):
        with patch("src.worker.tasks.restart_ingest.delay") as mock_delay:
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.post("/ingest/restart")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        mock_delay.assert_called_once()

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
            app.state.redis_cache = mock_redis_client
            app.state.vector_store = MagicMock()
            app.state.vector_store.count_entities.return_value = 0
            app.state.retriever = AsyncMock()
            app.state.llm = MagicMock()
            app.state.conversation_store = MagicMock()
            app.state.embedder = MagicMock()
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


class TestGoogleOAuthCallbackRouting:
    """Regression: GET /auth/google/callback must hit the API, not static 404."""

    @pytest.mark.integration
    async def test_oauth_callback_with_google_query_params_not_404(self, app_mocked):
        async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
            response = await client.get(
                "/auth/google/callback",
                params={
                    "code": "dummy-code",
                    "state": "dummy-state",
                    "iss": "https://accounts.google.com",
                },
            )
        assert response.status_code != 404
        assert response.status_code == 400


class TestDriveBootstrap:
    @pytest.mark.integration
    async def test_drive_bootstrap_local_mode_is_chat_ready(self, app_mocked):
        app_mocked.state.settings = Settings(ingest_source="local", local_source_folder="/tmp/docs")
        with patch("src.api.drive_routes.MetadataRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_drive_connection = AsyncMock(return_value=None)
            mock_repo.list_by_status = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app_mocked), base_url="http://test") as client:
                response = await client.get("/drive/bootstrap")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ingest_source"] == "local"
        assert payload["chat_ready"] is True
