"""Tests for src/rag/conversation.py — turns GREEN in Phase 6."""

from __future__ import annotations

import pytest

from src.rag.conversation import ConversationStore


class TestConversationStore:
    @pytest.fixture
    def store(self, mock_redis_client):
        store = ConversationStore.__new__(ConversationStore)
        store._redis = mock_redis_client
        return store

    def test_store_and_retrieve_history(self, store):
        store._redis.get.return_value = None
        store.append("conv-1", "user", "Hello")
        store._redis.get.return_value = '[{"role": "user", "content": "Hello"}]'
        history = store.get_history("conv-1")
        assert len(history) == 1
        assert history[0].role == "user"

    def test_empty_history_for_unknown_id(self, store):
        store._redis.get.return_value = None
        history = store.get_history("unknown")
        assert history == []

    def test_clear_history(self, store):
        store.clear("conv-1")
        store._redis.delete.assert_called_once_with("conv:conv-1")
