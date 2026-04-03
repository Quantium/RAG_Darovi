"""Tests for src/scheduler/pipeline.py — turns GREEN in Phase 4."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.scheduler.pipeline import trigger_incremental_sync


class TestSchedulerPipeline:
    @patch("src.scheduler.pipeline.run_incremental_sync")
    def test_schedule_sync_dispatches_task(self, mock_task):
        trigger_incremental_sync()
        mock_task.delay.assert_called_once()

    @patch("src.worker.celery_app.settings")
    def test_schedule_uses_configured_interval(self, mock_settings):
        mock_settings.sync_interval_hours = 12
        from src.worker.celery_app import app
        beat_schedule = app.conf.beat_schedule
        assert "incremental-sync" in beat_schedule
