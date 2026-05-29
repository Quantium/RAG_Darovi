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


def test_chatbot_response_health_endpoint():
    """Verify that GET /health returns HTTP 200 with status 'ok'."""
    module = _load_module()
    with patch.object(module, "RetrievalClient", autospec=True) as retrieval_cls, patch.object(
        module, "LLMService", autospec=True
    ) as llm_cls, patch.object(module.redis, "Redis", autospec=True):
        retrieval = retrieval_cls.return_value
        retrieval.retrieve = AsyncMock(
            return_value=module.ChatResponse(
                answer="ok",
                sources=[],
                conversation_id="c1",
            )
        )
        llm = llm_cls.return_value
        llm.answer = AsyncMock(return_value="ok")

        app = module.create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


def test_chatbot_ui_is_simple_and_has_no_side_tabs():
    """Verify that the chat UI root page contains the chat form and no document-type tabs."""
    module = _load_module()
    with patch.object(module, "RetrievalClient", autospec=True), patch.object(
        module, "LLMService", autospec=True
    ), patch.object(module.redis, "Redis", autospec=True):
        app = module.create_app()
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            html = response.text
            assert "chat-form" in html
            assert ">All<" not in html
            assert ">Docs<" not in html
            assert ">Sheets<" not in html
            assert ">PDFs<" not in html
