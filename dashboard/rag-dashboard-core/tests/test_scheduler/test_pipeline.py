"""Tests for src/scheduler/pipeline.py — turns GREEN in Phase 4."""

from __future__ import annotations

from unittest.mock import patch

from src.scheduler.pipeline import trigger_incremental_sync


class TestSchedulerPipeline:
    @patch("src.scheduler.pipeline.run_incremental_sync")
    def test_schedule_sync_dispatches_task(self, mock_task):
        """Verify trigger_incremental_sync calls run_incremental_sync.delay."""
        trigger_incremental_sync()
        mock_task.delay.assert_called_once()

    @patch("src.worker.celery_app.settings")
    def test_schedule_uses_configured_interval(self, mock_settings):
        """Verify the Celery beat schedule includes the poll-ready-text-for-embedding entry."""
        mock_settings.embedding_poll_interval_seconds = 120
        from src.worker.celery_app import app

        beat_schedule = app.conf.beat_schedule
        assert "poll-ready-text-for-embedding" in beat_schedule
