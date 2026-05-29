"""Tests for src/automation/engine.py — turns GREEN in Phase 6."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.automation.engine import AutomationEngine
from src.automation.templates import AutomationConfig, AutomationFilter, AutomationAction


class TestAutomationEngine:
    @pytest.fixture
    def engine(self):
        """Return an AutomationEngine configured with a PDF-filter on_new_file automation."""
        config = AutomationConfig(
            name="test-auto",
            trigger="on_new_file",
            filter=AutomationFilter(mime_type="application/pdf"),
            prompt="Extract data",
            action=AutomationAction(type="execute_sql", target="postgres"),
        )
        return AutomationEngine(
            retriever=AsyncMock(),
            llm=AsyncMock(),
            db_writer=AsyncMock(),
            configs=[config],
        )

    async def test_trigger_on_new_file(self, engine):
        """Verify run() calls the retriever when a matching on_new_file trigger fires."""
        engine._llm.chat.return_value = "INSERT INTO t VALUES (1);"
        await engine.run("on_new_file", {"mimeType": "application/pdf", "name": "invoice.pdf"})
        engine._retriever.retrieve.assert_called_once()

    async def test_execute_sql_action(self, engine):
        """Verify run() calls db_writer.execute_many when the automation action is execute_sql."""
        engine._llm.chat.return_value = "INSERT INTO t VALUES (1);"
        await engine.run("on_new_file", {"mimeType": "application/pdf", "name": "invoice.pdf"})
        engine._db_writer.execute_many.assert_called_once()

    async def test_skip_non_matching_file(self, engine):
        """Verify run() skips retrieval and execution when the file does not match the MIME filter."""
        await engine.run("on_new_file", {"mimeType": "text/plain", "name": "readme.txt"})
        engine._retriever.retrieve.assert_not_called()
