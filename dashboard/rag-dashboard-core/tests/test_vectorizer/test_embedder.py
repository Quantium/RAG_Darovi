"""Tests for src/vectorizer/embedder.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.vectorizer.embedder import BatchEmbedder


def _openai_response(vectors: list[list[float]]) -> MagicMock:
    """Build a mock httpx response in OpenAI /v1/embeddings format."""
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"data": data}
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    client = AsyncMock()
    client.post.return_value = _openai_response([[0.1] * 768])
    return client


class TestBatchEmbedder:
    async def test_embed_single_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["Hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768

    async def test_embed_batch(self, settings, mock_httpx_client):
        mock_httpx_client.post.return_value = _openai_response([[0.1] * 768 for _ in range(5)])
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert len(vectors) == 5

    async def test_batch_size_respected(self, settings, mock_httpx_client):
        settings_small = settings.model_copy(update={"embed_batch_size": 2})
        mock_httpx_client.post.return_value = _openai_response([[0.1] * 768, [0.2] * 768])
        embedder = BatchEmbedder(settings_small, client=mock_httpx_client)
        await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert mock_httpx_client.post.call_count == 3  # ceil(5/2)

    async def test_handles_empty_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([""])
        assert len(vectors[0]) == 768 or vectors[0] == [0.0] * 768

    async def test_retries_on_connect_error(self, settings, mock_httpx_client):
        mock_httpx_client.post.side_effect = [
            httpx.ConnectError("Connection refused"),
            _openai_response([[0.1] * 768]),
        ]
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["retry test"])
        assert len(vectors) == 1
