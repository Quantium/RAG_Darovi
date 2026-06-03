"""Stage 5 tests: chat hard-scopes to a licitación (selector, routing, rejection)."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    """Reload app.api in isolation to avoid cross-test state contamination."""
    for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
        del sys.modules[module_name]
    sys.path.insert(0, str(SERVICE_ROOT))
    try:
        return importlib.import_module("app.api")
    finally:
        sys.path = [entry for entry in sys.path if entry != str(SERVICE_ROOT)]


@contextmanager
def _app(module):
    """Yield (app, retrieval_mock) with external deps mocked."""
    with patch.object(module, "RetrievalClient", autospec=True) as rc_cls, patch.object(
        module, "LLMService", autospec=True
    ) as llm_cls, patch.object(module.redis, "Redis", autospec=True) as redis_cls:
        rc = rc_cls.return_value
        rc.retrieve = AsyncMock(return_value=SimpleNamespace(context="ctx", sources=[]))
        llm_cls.return_value.answer = AsyncMock(return_value="answer")
        redis_cls.from_url.return_value = MagicMock()
        app = module.create_app()
        yield app, rc


def test_licitaciones_endpoint_lists_active():
    """GET /licitaciones returns the active registry rows for the selector."""
    module = _load_module()
    listing = [{"slug": "obra_norte", "name": "Obra Norte", "collection": "rag_obra_norte"}]
    with _app(module) as (app, _rc):
        with patch.object(module, "_list_active_licitaciones_sync", return_value=listing):
            with TestClient(app) as client:
                resp = client.get("/licitaciones")
        assert resp.status_code == 200
        assert resp.json() == listing


def test_chat_requires_licitacion_returns_400():
    """A chat with no licitación is rejected (never silently hits a default tenant)."""
    module = _load_module()
    with _app(module) as (app, rc):
        app.dependency_overrides[module.require_session] = lambda: "tester"
        with TestClient(app) as client:
            resp = client.post("/chat", json={"query": "hola"})
        assert resp.status_code == 400
        rc.retrieve.assert_not_awaited()


def test_chat_unknown_licitacion_returns_404():
    """A chat for an unknown/inactive licitación is rejected."""
    module = _load_module()
    with _app(module) as (app, rc):
        app.dependency_overrides[module.require_session] = lambda: "tester"
        with patch.object(module, "_resolve_licitacion_sync", return_value=None):
            with TestClient(app) as client:
                resp = client.post("/chat", json={"query": "hola", "licitacion": "fantasma"})
        assert resp.status_code == 404
        rc.retrieve.assert_not_awaited()


def test_chat_routes_to_selected_licitacion():
    """A valid licitación scopes retrieval and persists the interaction to its schema."""
    module = _load_module()
    lic = {
        "slug": "obra_norte",
        "name": "Obra Norte",
        "schema_name": "lic_obra_norte",
        "collection": "rag_obra_norte",
    }
    with _app(module) as (app, rc):
        app.dependency_overrides[module.require_session] = lambda: "tester"
        with patch.object(module, "_resolve_licitacion_sync", return_value=lic), patch.object(
            module, "_save_interaction_sync", return_value=7
        ) as save_mock:
            with TestClient(app) as client:
                resp = client.post("/chat", json={"query": "hola", "licitacion": "obra_norte"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["interaction_id"] == 7
        # Retrieval was scoped to the selected licitación.
        assert rc.retrieve.await_args.kwargs["licitacion"] == "obra_norte"
        # Persistence targeted the licitación schema (last positional arg of _save_interaction_sync).
        assert save_mock.call_args.args[-1] == "lic_obra_norte"


def test_conversation_key_is_namespaced_by_slug():
    """Conversation history keys are namespaced per licitación; empty slug keeps the legacy key."""
    module = _load_module()
    store = module.ConversationStore
    assert store._key("c1", "obra_norte") == "chatbot:conv:obra_norte:c1"
    assert store._key("c1") == "chatbot:conv:c1"
