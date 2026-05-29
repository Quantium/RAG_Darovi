from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    """Reload the app.api module in isolation to avoid cross-test state contamination.

    Returns:
        The freshly imported app.api module object.
    """
    for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
        del sys.modules[module_name]
    sys.path.insert(0, str(SERVICE_ROOT))
    try:
        return importlib.import_module("app.api")
    finally:
        sys.path = [entry for entry in sys.path if entry != str(SERVICE_ROOT)]


def test_retrieval_admin_health_endpoint():
    """Verify that GET /health returns HTTP 200 with status 'ok'."""
    module = _load_module()
    with patch.object(module, "MetadataService", autospec=True) as metadata_cls, patch.object(
        module, "Retriever", autospec=True
    ) as retriever_cls, patch.object(module, "LLMService", autospec=True) as llm_cls, patch.object(
        module.redis, "Redis", autospec=True
    ) as redis_cls:
        metadata = metadata_cls.return_value
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
        metadata.close = AsyncMock(return_value=None)
        retriever = retriever_cls.return_value
        retriever.retrieve = AsyncMock(return_value=[])
        llm = llm_cls.return_value
        llm.answer = AsyncMock(return_value="ok")
        redis_cls.from_url.return_value = MagicMock()

        app = module.create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


