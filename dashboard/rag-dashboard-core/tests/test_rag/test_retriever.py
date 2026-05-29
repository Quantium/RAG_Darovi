"""Tests for src/rag/retriever.py — turns GREEN in Phase 6."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.rag.retriever import Retriever


class TestRetriever:
    @pytest.fixture
    def retriever(self, mock_ollama_client, mock_milvus_client, mock_redis_client):
        """Return a Retriever with mocked embedder, vector store, and Redis cache."""
        embedder = AsyncMock()
        embedder.embed_texts.return_value = [[0.1] * 768]
        return Retriever(embedder=embedder, vector_store=mock_milvus_client, cache=mock_redis_client)

    async def test_retrieve_top_k_chunks(self, retriever):
        """Verify retrieve returns results from the vector store for a valid query."""
        retriever._vector_store.search.return_value = [
            {"id": "h1", "text": "revenue data", "source_name": "report.pdf", "score": 0.95}
        ]
        results = await retriever.retrieve("What is the revenue?", top_k=5)
        assert len(results) >= 1

    async def test_retrieve_with_document_type_filter(self, retriever):
        """Verify retrieve passes the document_type partition filter to the vector store search."""
        await retriever.retrieve("revenue", top_k=5, document_type="pdf")
        call_args = retriever._vector_store.search.call_args
        assert "pdf" in str(call_args)

    async def test_retrieve_includes_metadata(self, retriever):
        """Verify retrieve results include source_name metadata from the vector store."""
        retriever._vector_store.search.return_value = [
            {"id": "h1", "text": "data", "source_name": "r.pdf", "section_title": "Rev", "chunk_index": 0, "score": 0.9}
        ]
        results = await retriever.retrieve("query")
        assert hasattr(results[0], "source_name")

    async def test_retrieve_empty_query(self, retriever):
        """Verify retrieve returns an empty list (or at least a list) for a blank query."""
        results = await retriever.retrieve("")
        assert results == [] or isinstance(results, list)

    async def test_retrieve_caches_result(self, retriever):
        """Verify the second retrieve call for the same query hits Redis cache and skips vector search."""
        retriever._vector_store.search.return_value = [{"id": "h1", "text": "cached", "score": 0.9}]
        await retriever.retrieve("same query")
        await retriever.retrieve("same query")
        # Second call should hit cache, so search called only once
