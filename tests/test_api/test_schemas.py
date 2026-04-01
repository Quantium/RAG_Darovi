"""Tests for src/api/schemas.py — turns GREEN in Phase 7."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, ChatResponse, SourceReference, StatusResponse


class TestAPISchemas:
    def test_chat_request_validation(self):
        req = ChatRequest(query="What is revenue?")
        assert req.query == "What is revenue?"

    def test_chat_request_rejects_empty(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="")

    def test_chat_response_structure(self):
        resp = ChatResponse(
            answer="Revenue was $1.2M",
            sources=[SourceReference(
                source_file_id="f1", source_name="report.pdf",
                section_title="Revenue", chunk_index=0,
                text_preview="Total revenue...", score=0.95,
            )],
            conversation_id="conv-123",
        )
        assert resp.answer == "Revenue was $1.2M"
        assert len(resp.sources) == 1

    def test_status_response_structure(self):
        resp = StatusResponse(total_files=100, pending=10, downloaded=20, converted=30, embedded=35, failed=5)
        assert resp.total_files == 100
        assert resp.failed == 5
