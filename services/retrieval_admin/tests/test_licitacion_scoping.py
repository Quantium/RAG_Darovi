"""Stage 5 tests: /retrieve resolves the Milvus collection per licitación, server-side."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
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
def _client(module):
    """Yield (client, retriever_mock, metadata_mock) with external deps mocked."""
    with patch.object(module, "MetadataService", autospec=True) as md_cls, patch.object(
        module, "Retriever", autospec=True
    ) as rt_cls, patch.object(module, "LLMService", autospec=True) as llm_cls, patch.object(
        module.redis, "Redis", autospec=True
    ) as redis_cls:
        md = md_cls.return_value
        md.close = AsyncMock(return_value=None)
        md.resolve_active_collection = AsyncMock(return_value="rag_obra_norte")
        rt = rt_cls.return_value
        rt.retrieve = AsyncMock(return_value=[])
        llm_cls.return_value.answer = AsyncMock(return_value="ok")
        redis_cls.from_url.return_value = MagicMock()
        app = module.create_app()
        with TestClient(app) as client:
            yield client, rt, md


def test_retrieve_resolves_collection_from_licitacion():
    """A valid licitación slug is resolved to its collection and passed to the retriever."""
    module = _load_module()
    with _client(module) as (client, rt, md):
        resp = client.post("/retrieve", json={"query": "hola", "licitacion": "obra_norte"})
        assert resp.status_code == 200
        md.resolve_active_collection.assert_awaited_once_with("obra_norte")
        assert rt.retrieve.await_args.kwargs["collection"] == "rag_obra_norte"


def test_retrieve_unknown_licitacion_returns_404():
    """An unknown/inactive licitación is rejected and never reaches the retriever."""
    module = _load_module()
    with _client(module) as (client, rt, md):
        md.resolve_active_collection = AsyncMock(return_value=None)
        resp = client.post("/retrieve", json={"query": "hola", "licitacion": "fantasma"})
        assert resp.status_code == 404
        rt.retrieve.assert_not_awaited()


def test_retrieve_without_licitacion_uses_default_collection():
    """Omitting the licitación leaves collection=None (retriever falls back to the global one)."""
    module = _load_module()
    with _client(module) as (client, rt, md):
        resp = client.post("/retrieve", json={"query": "hola"})
        assert resp.status_code == 200
        md.resolve_active_collection.assert_not_awaited()
        assert rt.retrieve.await_args.kwargs["collection"] is None


def test_retrieve_invalid_slug_returns_400():
    """A malformed slug is rejected before any registry/Milvus access."""
    module = _load_module()
    with _client(module) as (client, rt, md):
        resp = client.post("/retrieve", json={"query": "hola", "licitacion": "Bad Slug!"})
        assert resp.status_code == 400
        md.resolve_active_collection.assert_not_awaited()
        rt.retrieve.assert_not_awaited()
