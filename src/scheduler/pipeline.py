from __future__ import annotations

from src.worker.celery_app import app
from src.worker.tasks import run_incremental_sync


@app.task(name="src.scheduler.pipeline.trigger_incremental_sync")
def trigger_incremental_sync() -> None:
    """Entry point for Celery Beat. Delegates to the sync orchestrator."""
    run_incremental_sync.delay()


def schedule_sync() -> None:
    """Manual trigger to start a sync immediately via Celery."""
    run_incremental_sync.delay()
