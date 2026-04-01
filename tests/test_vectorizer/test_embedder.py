"""Tests for src/vectorizer/embedder.py — turns GREEN in Phase 5."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.vectorizer.embedder import BatchEmbedder


class TestBatchEmbedder:
    async def test_embed_single_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["Hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768

    async def test_embed_batch(self, settings, mock_httpx_client):
        mock_httpx_client.post.return_value.json.return_value = {
            "embeddings": [[0.1] * 768 for _ in range(5)]
        }
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert len(vectors) == 5

    async def test_batch_size_respected(self, settings, mock_httpx_client):
        settings_small = settings.model_copy(update={"embed_batch_size": 2})
        mock_httpx_client.post.return_value.json.return_value = {"embeddings": [[0.1] * 768, [0.2] * 768]}
        embedder = BatchEmbedder(settings_small, client=mock_httpx_client)
        await embedder.embed_texts([f"text {i}" for i in range(5)])
        assert mock_httpx_client.post.call_count == 3  # ceil(5/2)

    async def test_handles_empty_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts([""])
        assert len(vectors[0]) == 768 or vectors[0] == [0.0] * 768

    async def test_retries_on_ollama_error(self, settings, mock_httpx_client):
        import httpx
        mock_httpx_client.post.side_effect = [
            httpx.ConnectError("Connection refused"),
            AsyncMock(json=lambda: {"embeddings": [[0.1] * 768]}, status_code=200, raise_for_status=lambda: None),
        ]
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["retry test"])
        assert len(vectors) == 1
