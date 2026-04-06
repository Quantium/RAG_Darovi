"""Tests for src/vectorizer/embedder.py — turns GREEN in Phase 5."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.vectorizer.embedder import BatchEmbedder


class TestBatchEmbedder:
    async def test_embed_single_text(self, settings, mock_httpx_client):
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["Hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768

    async def test_embed_batch(self, settings, mock_httpx_client):
        mock_httpx_client.post.return_value.json.return_value = {"embeddings": [[0.1] * 768 for _ in range(5)]}
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

    async def test_fallback_to_legacy_on_api_embed_404(self, settings, mock_httpx_client):
        """Ollama before 0.3.4 returns 404 on /api/embed; use /api/embeddings per text."""

        def post_impl(url: str, **kwargs: object) -> MagicMock:
            if str(url).rstrip("/").endswith("/api/embed"):
                r = MagicMock()
                r.status_code = 404
                return r
            if str(url).rstrip("/").endswith("/api/embeddings"):
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {"embedding": [0.1] * 768}
                r.raise_for_status = MagicMock()
                return r
            raise AssertionError(f"unexpected URL: {url}")

        mock_httpx_client.post.side_effect = post_impl
        embedder = BatchEmbedder(settings, client=mock_httpx_client)
        vectors = await embedder.embed_texts(["Hello world"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768
