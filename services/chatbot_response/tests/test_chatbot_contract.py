from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _load_retrieval_client_module():
    """Reload the app.retrieval_client module in isolation to avoid cross-test state contamination.

    Returns:
        The freshly imported app.retrieval_client module object.
    """
    for module_name in [name for name in list(sys.modules) if name == "app" or name.startswith("app.")]:
        del sys.modules[module_name]
    sys.path.insert(0, str(SERVICE_ROOT))
    try:
        return importlib.import_module("app.retrieval_client")
    finally:
        sys.path = [entry for entry in sys.path if entry != str(SERVICE_ROOT)]


@pytest.mark.asyncio
async def test_retrieval_client_parses_contract_response() -> None:
    """Verify that RetrievalClient correctly deserializes a valid retrieval service response."""
    module = _load_retrieval_client_module()
    settings = module.Settings(retrieval_admin_base_url="http://retrieval-admin:8010")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "query": "hello",
        "context": "[Source: file.txt | Section: s1]\\nhello",
        "sources": [
            {
                "source_file_id": "f1",
                "source_name": "file.txt",
                "section_title": "s1",
                "chunk_index": 0,
                "text_preview": "hello",
                "score": 0.9,
            }
        ],
    }

    with patch.object(module.httpx, "AsyncClient", autospec=True) as client_cls:
        client = client_cls.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=fake_response)
        api_client = module.RetrievalClient(settings)
        response = await api_client.retrieve(query="hello", top_k=5, document_type="doc", api_key="k")
        assert response.query == "hello"
        assert response.sources[0].source_name == "file.txt"


@pytest.mark.asyncio
async def test_retrieval_client_forwards_licitacion_in_payload() -> None:
    """Verify RetrievalClient includes the licitación slug in the request body when provided."""
    module = _load_retrieval_client_module()
    settings = module.Settings(retrieval_admin_base_url="http://retrieval-admin:8010")

    captured: dict = {}
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"query": "q", "context": "c", "sources": []}

    async def _post(url, headers=None, json=None):
        captured.update(json or {})
        return fake_response

    with patch.object(module.httpx, "AsyncClient", autospec=True) as client_cls:
        client = client_cls.return_value.__aenter__.return_value
        client.post = AsyncMock(side_effect=_post)
        api_client = module.RetrievalClient(settings)
        await api_client.retrieve(query="q", licitacion="obra_norte")

    assert captured["licitacion"] == "obra_norte"
