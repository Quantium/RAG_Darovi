"""Tests for src/vectorizer/milvus_store.py — turns GREEN in Phase 5."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.vectorizer.milvus_store import MilvusStore


class TestMilvusStore:
    @pytest.fixture
    def store(self, settings, mock_milvus_client):
        """Return a MilvusStore with a mock client injected."""
        return MilvusStore(settings, client=mock_milvus_client)

    def test_create_collection(self, store, mock_milvus_client):
        """Verify create_collection calls the mock client's create_collection method."""
        store.create_collection()
        mock_milvus_client.create_collection.assert_called_once()

    def test_upsert_chunks(self, store, mock_milvus_client):
        """Verify upsert calls the mock client's insert method with the provided chunks and embeddings."""
        chunks = [{"id": "h1", "source_file_id": "f1", "text": "hello", "document_type": "doc"}]
        embeddings = [[0.1] * 768]
        store.upsert(chunks, embeddings)
        mock_milvus_client.insert.assert_called_once()

    def test_search_returns_results(self, store, mock_milvus_client):
        """Verify search returns a list of result dicts from the mock client."""
        mock_milvus_client.search.return_value = [
            [MagicMock(id="h1", score=0.95, entity=MagicMock(get=lambda k: "val"))]
        ]
        results = store.search([0.1] * 768, top_k=5)
        assert isinstance(results, list)

    def test_search_with_partition_filter(self, store, mock_milvus_client):
        """Verify search passes the partition name to the mock client's search call."""
        store.search([0.1] * 768, top_k=5, partition="pdf")
        call_kwargs = mock_milvus_client.search.call_args
        assert "pdf" in str(call_kwargs)

    def test_delete_by_source_file(self, store, mock_milvus_client):
        """Verify delete_by_source calls the mock client's delete method."""
        store.delete_by_source("f1")
        mock_milvus_client.delete.assert_called_once()

    def test_collection_exists_check(self, store, mock_milvus_client):
        """Verify collection_exists returns True when the mock client reports the collection exists."""
        mock_milvus_client.has_collection.return_value = True
        assert store.collection_exists() is True

    def test_drop_collection_if_exists(self, store, mock_milvus_client):
        """Verify drop_collection_if_exists calls the mock client's drop_collection when it exists."""
        mock_milvus_client.has_collection.return_value = True
        store.drop_collection_if_exists()
        mock_milvus_client.drop_collection.assert_called_once()
