from __future__ import annotations

import structlog
from celery import Celery, Task
from config.settings import Settings
from src.logging import configure_logging

logger = structlog.get_logger()

settings = Settings()
configure_logging()

app = Celery(
    "rag_darovi",
    broker=settings.redis_broker_url,
    backend=settings.redis_result_url,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "src.worker.tasks.download_file": {"queue": "download"},
        "src.worker.tasks.convert_file": {"queue": "convert"},
        "src.worker.tasks.vision_extract": {"queue": "vision"},
        "src.worker.tasks.embed_file": {"queue": "embed"},
    },
    beat_schedule={
        "incremental-sync": {
            "task": "src.scheduler.pipeline.trigger_incremental_sync",
            "schedule": settings.sync_interval_hours * 3600,
        },
    },
)

app.autodiscover_tasks(["src.worker", "src.scheduler"])


class RetryableTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Set metadata status to 'failed' when all retries are exhausted."""
        file_meta = args[0] if args else kwargs.get("file_meta", {})
        drive_file_id = file_meta.get("drive_file_id") or file_meta.get("id", "unknown")
        logger.error(
            "task.permanently_failed",
            task=self.name,
            drive_file_id=drive_file_id,
            error=str(exc),
            retries_exhausted=self.max_retries,
        )
        try:
            from src.worker.task_helpers import build_metadata_repo

            repo, cleanup = build_metadata_repo()
            repo.update_status_sync(drive_file_id, "failed", error_message=str(exc))
            cleanup()
        except Exception as inner_exc:
            logger.error("task.on_failure_error", error=str(inner_exc))


class VisionRetryableTask(RetryableTask):
    """Tighter retry policy for the VLM step.

    The vision pipeline already retries individual pages internally (with a
    downscale path) and tracks repeated failures via a Redis circuit
    breaker. Hitting the broad Celery autoretry too aggressively would
    pin GPU resources, so we cap retries at 3 with a faster backoff.
    """

    max_retries = 3
    retry_backoff_max = 120

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        file_meta = args[0] if args else {}
        drive_file_id = file_meta.get("drive_file_id", "unknown") if isinstance(file_meta, dict) else "unknown"
        logger.error(
            "task.vision_permanently_failed",
            task=self.name,
            drive_file_id=drive_file_id,
            error=str(exc),
        )
        try:
            from src.worker.task_helpers import build_metadata_repo

            repo, cleanup = build_metadata_repo()
            repo.update_status_sync(drive_file_id, "vision_failed", error_message=str(exc))
            cleanup()
        except Exception as inner_exc:
            logger.error("task.on_failure_error", error=str(inner_exc))
