from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import app.api as api_module


def test_health() -> None:
    with patch.object(api_module, "MetadataService", autospec=True) as metadata_cls, patch.object(
        api_module, "Retriever", autospec=True
    ) as retriever_cls, patch.object(api_module, "LLMService", autospec=True) as llm_cls, patch.object(
        api_module.redis, "Redis", autospec=True
    ) as redis_cls:
        metadata = metadata_cls.return_value
        metadata.close = AsyncMock(return_value=None)
        metadata.get_status_counts = AsyncMock(
            return_value={
                "total_files": 0,
                "pending": 0,
                "downloaded": 0,
                "converted": 0,
                "embedded": 0,
                "failed": 0,
                "vision_pending": 0,
                "vision_processing": 0,
                "vision_failed": 0,
            }
        )
        retriever = retriever_cls.return_value
        retriever.retrieve = AsyncMock(return_value=[])
        llm = llm_cls.return_value
        llm.answer = AsyncMock(return_value="ok")
        redis_cls.from_url.return_value = MagicMock()

        app = api_module.create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
