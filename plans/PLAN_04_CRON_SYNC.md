# Phase 4: Celery Workers & Scheduled Sync (Cron)

**Goal**: Implement Celery configuration, the three core worker tasks (download, convert, embed), and the Celery Beat scheduler that triggers incremental sync from Google Drive on a configurable interval.

**Depends on**: Phase 3 (storage, metadata, drive, converters, converter factory, structlog all implemented).

**Success Criteria**: Tests in `test_worker/` and `test_scheduler/` turn GREEN (except `test_embed_task_calls_embedder`, which stays RED until Phase 5). `celery -A src.worker.celery_app worker` starts. Celery Beat triggers the sync pipeline on schedule. Task chains (download → convert → embed placeholder) execute end-to-end.

---

## Step 4.1 — Celery Application Configuration

**File**: `src/worker/celery_app.py`

**Setup**:

```python
from __future__ import annotations

from celery import Celery, Task
from config.settings import Settings
from src.logging import configure_logging

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
```

**Key design**:
- Three separate queues (`download`, `convert`, `embed`) for independent scaling.
- `task_acks_late=True` + `worker_prefetch_multiplier=1` for at-least-once delivery.
- Beat schedule configurable via `SYNC_INTERVAL_HOURS` env var.
- `configure_logging()` is called at module load so all workers get structured logging.
- Beat schedule points to `src.scheduler.pipeline.trigger_incremental_sync` (Step 4.5).

---

## Step 4.2 — Base Task with Retry & Failure Handling

**File**: `src/worker/celery_app.py` (add to same file)

```python
import asyncio
import structlog
from celery import Task

logger = structlog.get_logger()


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
            repo.update_status(drive_file_id, "failed", error_message=str(exc))
            cleanup()
        except Exception as inner_exc:
            logger.error("task.on_failure_error", error=str(inner_exc))
```

All pipeline tasks inherit from `RetryableTask`. The `on_failure` hook ensures files don't get stuck in intermediate states.

---

## Step 4.3 — Task Dependency Helper

**File**: `src/worker/task_helpers.py`

Centralizes service construction for Celery tasks. Each task invocation builds its own short-lived dependencies.

> **Critical design decision**: Celery tasks run synchronously. The original design used `asyncio.run()` to bridge async sessions, but `AsyncSession` is bound to the event loop that created it and cannot be used outside that loop. Instead, Celery tasks use **synchronous SQLAlchemy sessions** via `psycopg2`, reserving `asyncpg` for FastAPI. The `MetadataRepository` is updated to accept either session type (see Phase 3), but for Celery we always use the sync variant.

```python
from __future__ import annotations

from typing import Callable

from config.settings import Settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.storage.backend import MinIOStorage
from src.metadata.repository import SyncMetadataRepository


def build_settings() -> Settings:
    return Settings()


def build_storage(settings: Settings | None = None) -> MinIOStorage:
    s = settings or build_settings()
    return MinIOStorage(s)


def build_metadata_repo(settings: Settings | None = None) -> tuple[SyncMetadataRepository, Callable[[], None]]:
    """Return (repo, cleanup_fn). Caller must call cleanup_fn() when done.

    Uses synchronous psycopg2 engine — safe to use in Celery tasks without
    event loop issues.
    """
    s = settings or build_settings()
    engine = create_engine(s.database_url_sync.get_secret_value())
    session = Session(engine)
    repo = SyncMetadataRepository(session)

    def cleanup() -> None:
        session.close()
        engine.dispose()

    return repo, cleanup


MIME_TO_DOC_TYPE: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.google-apps.document": "doc",
    "application/vnd.google-apps.spreadsheet": "sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/plain": "doc",
    "text/markdown": "doc",
    "text/html": "html",
    "text/csv": "sheet",
}


def derive_document_type(mime_type: str) -> str:
    return MIME_TO_DOC_TYPE.get(mime_type, "doc")
```

> **`SyncMetadataRepository`**: A synchronous mirror of `MetadataRepository` that wraps a `sqlalchemy.orm.Session` instead of `AsyncSession`. Both share the same SQLAlchemy models (`FileRecord`, `SyncState`) and the same method signatures, but the sync variant uses blocking calls. This is defined in `src/metadata/repository.py` alongside the async version. See Phase 3 Step 3.2.

> **Note**: This module follows Dependency Inversion — tasks depend on the helpers, not on concrete construction details. The helpers are also mockable in tests.

---

## Step 4.4 — Worker Tasks

**File**: `src/worker/tasks.py`

### Task: `run_incremental_sync`

Orchestrator task — uses plain `Task` base (not `RetryableTask`) to avoid retrying the entire sync when individual files have their own retry logic.

**Distributed lock**: Uses a Redis `SET NX` lock to prevent concurrent syncs from overlapping (e.g., two Beat instances, or a manual `ingest` while Beat fires). The lock expires after 30 minutes (safety net for crashed tasks):

```python
import asyncio
import structlog
import redis
from src.worker.celery_app import app, RetryableTask
from src.worker.task_helpers import (
    build_settings, build_storage, build_metadata_repo, derive_document_type,
)

logger = structlog.get_logger()

SYNC_LOCK_KEY = "rag:sync:lock"
SYNC_LOCK_TTL = 1800  # 30 minutes


@app.task(bind=True, max_retries=1)
def run_incremental_sync(self):
    """Orchestrate: fetch changed files from Drive, dispatch per-file pipelines.

    Acquires a distributed lock to prevent concurrent syncs.
    """
    from src.drive.auth import build_drive_service
    from src.drive.downloader import DriveDownloader

    settings = build_settings()
    r = redis.Redis.from_url(settings.redis_broker_url)

    if not r.set(SYNC_LOCK_KEY, "1", nx=True, ex=SYNC_LOCK_TTL):
        logger.warning("sync.skipped_concurrent", reason="Another sync is already running")
        return

    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        service = build_drive_service(settings.google_application_credentials)
        downloader = DriveDownloader(
            drive_service=service, storage=storage,
            metadata_repo=repo, settings=settings,
        )
        changed_files, deleted_ids = asyncio.run(downloader.incremental_sync())
        logger.info("sync.files_found", changed=len(changed_files), deleted=len(deleted_ids))

        for file_meta in changed_files:
            dispatch_file_pipeline(file_meta)

        for drive_file_id in deleted_ids:
            delete_file_vectors.delay(drive_file_id)

        logger.info("sync.dispatched", changed=len(changed_files), deleted=len(deleted_ids))
    finally:
        r.delete(SYNC_LOCK_KEY)
        cleanup()
```

### Task: `download_file`

> **Async bridging**: The `DriveDownloader` is `async` (Google API calls). Since Celery tasks are synchronous, we bridge with a single `asyncio.run()` call per task. The metadata repo is now sync (via `SyncMetadataRepository`), so only the Drive API calls need the async bridge. The downloader accepts either repo type.

```python
@app.task(base=RetryableTask, bind=True)
def download_file(self, file_meta: dict) -> dict:
    """Download a single file from Drive to MinIO."""
    from src.drive.auth import build_drive_service
    from src.drive.downloader import DriveDownloader

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        service = build_drive_service(settings.google_application_credentials)
        downloader = DriveDownloader(
            drive_service=service, storage=storage,
            metadata_repo=repo, settings=settings,
        )
        minio_key = asyncio.run(downloader.download_file(file_meta))

        if minio_key is None:
            logger.info("task.download.skipped", drive_file_id=file_meta["id"])
            return {"skipped": True, "drive_file_id": file_meta["id"]}

        logger.info("task.download.completed", drive_file_id=file_meta["id"], minio_key=minio_key)
        return {
            "drive_file_id": file_meta["id"],
            "minio_raw_key": minio_key,
            "mime_type": file_meta["mimeType"],
            "name": file_meta["name"],
        }
    finally:
        cleanup()
```

### Task: `convert_file`

Uses the `get_converter()` factory from Phase 3 — no inline MIME selection:

```python
@app.task(base=RetryableTask, bind=True)
def convert_file(self, download_result: dict) -> dict:
    """Convert a raw file to plain text."""
    from src.converter import get_converter

    if download_result.get("skipped"):
        return download_result

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    drive_file_id = download_result["drive_file_id"]
    try:
        raw_bytes = storage.download(settings.minio_bucket_raw, download_result["minio_raw_key"])
        try:
            converter = get_converter(download_result["mime_type"])
        except ValueError:
            repo.update_status(drive_file_id, "skipped", error_message=f"Unsupported MIME: {download_result['mime_type']}")
            logger.warning("task.convert.unsupported", drive_file_id=drive_file_id, mime_type=download_result["mime_type"])
            return {"skipped": True, "drive_file_id": drive_file_id}

        text = converter.convert(raw_bytes, download_result["name"], download_result["mime_type"])

        text_key = f"{drive_file_id}.txt"
        storage.upload(settings.minio_bucket_text, text_key, text.encode("utf-8"))
        repo.update_status(drive_file_id, "converted")

        logger.info("task.convert.completed", drive_file_id=drive_file_id, text_key=text_key)
        return {
            "drive_file_id": drive_file_id,
            "minio_text_key": text_key,
            "name": download_result["name"],
            "document_type": derive_document_type(download_result["mime_type"]),
        }
    finally:
        cleanup()
```

### Task: `embed_file` (placeholder — completed in Phase 5)

```python
@app.task(base=RetryableTask, bind=True)
def embed_file(self, convert_result: dict) -> dict:
    """Chunk, embed, and store vectors. Placeholder until Phase 5."""
    if convert_result.get("skipped"):
        return convert_result

    raise NotImplementedError(
        "embed_file is a placeholder. Implement in Phase 5 with BatchEmbedder + MilvusStore."
    )
```

### Task: `delete_file_vectors`

Handles cleanup when a file is deleted or trashed in Google Drive:

```python
@app.task(base=RetryableTask, bind=True)
def delete_file_vectors(self, drive_file_id: str) -> dict:
    """Remove vectors from Milvus, files from MinIO, and metadata from PostgreSQL."""
    from src.vectorizer.milvus_store import MilvusStore

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        store = MilvusStore(settings)
        store.delete_by_source(drive_file_id)
        logger.info("task.delete.vectors_removed", drive_file_id=drive_file_id)

        # Clean up MinIO objects
        raw_key = f"{drive_file_id}"
        text_key = f"{drive_file_id}.txt"
        try:
            storage.delete(settings.minio_bucket_raw, raw_key)
            storage.delete(settings.minio_bucket_text, text_key)
        except Exception as exc:
            logger.warning("task.delete.storage_cleanup_partial", drive_file_id=drive_file_id, error=str(exc))

        repo.delete_file_record(drive_file_id)
        logger.info("task.delete.completed", drive_file_id=drive_file_id)
        return {"drive_file_id": drive_file_id, "deleted": True}
    finally:
        cleanup()
```

> **Note**: `delete_file_record` is a new method on `SyncMetadataRepository` / `MetadataRepository` that deletes the `FileRecord` row. Added to Phase 3 Step 3.2.

---

### Task Chaining

```python
from celery import chain


def dispatch_file_pipeline(file_meta: dict) -> None:
    """Build and dispatch the download → convert → embed chain for one file."""
    pipeline = chain(
        download_file.s(file_meta),
        convert_file.s(),
        embed_file.s(),
    )
    pipeline.apply_async()
```

> **Note on `.s()` vs `.si()`**: The chain uses `.s()` (mutable signature) so each task receives the previous task's return dict as its first argument. Do NOT use `.si()` (immutable) here — that would discard results between stages.

---

## Step 4.5 — Scheduler Pipeline

**File**: `src/scheduler/pipeline.py`

A Celery task registered via Beat schedule. This is the entry point that Beat calls:

```python
from __future__ import annotations

from src.worker.celery_app import app
from src.worker.tasks import run_incremental_sync


@app.task(name="src.scheduler.pipeline.trigger_incremental_sync")
def trigger_incremental_sync() -> None:
    """Entry point for Celery Beat. Delegates to the sync orchestrator."""
    run_incremental_sync.delay()
```

> **Design note**: This thin wrapper exists so that: (1) Beat has a named task to schedule, (2) the sync logic is testable independently, and (3) future enhancements (e.g., locking to prevent concurrent syncs) can be added here.

**Tests to turn GREEN**: `tests/test_scheduler/test_pipeline.py`

---

## Step 4.6 — Error Handling & Observability

**Retry behavior**:
- All pipeline tasks use `RetryableTask` base with exponential backoff (max 5 retries, max 10min delay).
- The orchestrator (`run_incremental_sync`) uses plain `Task` with `max_retries=1` to avoid re-dispatching all files.
- After exhausting retries, `RetryableTask.on_failure` (Step 4.2) updates the metadata DB status to `failed` with the error message.

**Structured logging** in each task:

```python
import structlog
logger = structlog.get_logger()

logger.info("task.started", task="download_file", drive_file_id=file_meta["id"])
logger.info("task.completed", task="download_file", drive_file_id=file_meta["id"], minio_key=key)
logger.error("task.failed", task="download_file", drive_file_id=file_meta["id"], error=str(exc))
```

**Distributed tracing**: Propagate `trace_id` via Celery custom headers:

```python
from uuid import uuid4

@app.task(bind=True)
def download_file(self, file_meta):
    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    logger = structlog.get_logger().bind(trace_id=trace_id)
    ...
```

When dispatching chains, pass the trace_id in headers:

```python
def dispatch_file_pipeline(file_meta: dict) -> None:
    trace_id = str(uuid4())
    pipeline = chain(
        download_file.s(file_meta),
        convert_file.s(),
        embed_file.s(),
    )
    pipeline.apply_async(headers={"trace_id": trace_id})
```

---

## Step 4.7 — Skipped File Handling

When `download_file` returns `{"skipped": True, ...}` (file unchanged), downstream tasks must propagate the skip without doing work:

- `convert_file`: checks `download_result.get("skipped")` → returns immediately.
- `embed_file`: checks `convert_result.get("skipped")` → returns immediately.

This prevents unnecessary processing and keeps the chain intact (no broken links).

---

## Step 4.8 — Tests to Turn GREEN

Run all worker and scheduler tests:

```bash
pytest tests/test_worker/ tests/test_scheduler/ -v
```

| Test | Phase 4 Status | Validated Behavior |
|---|---|---|
| `test_download_task_calls_downloader` | GREEN | Downloader invoked, status updated |
| `test_convert_task_calls_converter` | GREEN | Factory used, text stored |
| `test_convert_task_skips_unsupported_mime` | GREEN | Unsupported MIME → status `skipped` |
| `test_embed_task_calls_embedder` | **xfail** (Phase 5) | Placeholder raises `NotImplementedError` |
| `test_task_chain_download_convert_embed` | GREEN | Chain wired correctly |
| `test_task_retry_on_failure` | GREEN | Retry triggered with backoff |
| `test_task_marks_failed_after_max_retries` | GREEN | `on_failure` sets status to `failed` |
| `test_delete_file_vectors_removes_all` | GREEN | Milvus + MinIO + PG cleaned up |
| `test_sync_acquires_distributed_lock` | GREEN | Redis NX lock prevents concurrent syncs |
| `test_sync_dispatches_deletions` | GREEN | Deleted file IDs trigger `delete_file_vectors` |
| `test_schedule_sync_dispatches_task` | GREEN | `trigger_incremental_sync` calls sync |
| `test_schedule_uses_configured_interval` | GREEN | Beat schedule reads interval |

**SC**: `pytest tests/test_worker/ tests/test_scheduler/ -v` → all pass (embed test marked `xfail`, turns GREEN and removes `xfail` in Phase 5).

---

## Step 4.9 — Docker Verification

Start workers and beat:

```bash
# Terminal 1: Worker (listens on all three queues)
celery -A src.worker.celery_app worker --loglevel=info -Q download,convert,embed

# Terminal 2: Beat
celery -A src.worker.celery_app beat --loglevel=info
```

Verify:
1. Worker connects to Redis broker — look for `connected to redis://...` in output.
2. Beat schedules `incremental-sync` task — look for `Scheduler: Sending due task`.
3. Manually trigger:
   ```bash
   python -c "from src.worker.tasks import run_incremental_sync; run_incremental_sync.delay()"
   ```
4. Check Redis for task results:
   ```bash
   docker compose exec redis redis-cli KEYS "celery-task-meta-*"
   ```

---

## Output of This Phase

- `src/worker/celery_app.py` — Celery config with isolated Redis DBs (broker=0, results=1), queues, `RetryableTask` with sync `on_failure`, beat schedule, `configure_logging()` call
- `src/worker/task_helpers.py` — Dependency construction using **synchronous** `psycopg2` sessions (`build_storage`, `build_metadata_repo` → `SyncMetadataRepository`, `derive_document_type` with expanded MIME map)
- `src/worker/tasks.py` — `run_incremental_sync` (with distributed lock + deletion dispatch), `download_file`, `convert_file` (with unsupported MIME handling), `embed_file` (placeholder), `delete_file_vectors` (full cleanup), `dispatch_file_pipeline`
- `src/scheduler/pipeline.py` — `trigger_incremental_sync` Celery task (Beat entry point)
- Worker tasks properly chained: download → convert → embed (via `.s()`)
- Distributed Redis lock prevents concurrent sync runs
- `on_failure` handler updates metadata status to `failed` on exhausted retries (sync DB call)
- Skipped-file propagation through the chain
- File deletion flow: Milvus vectors + MinIO objects + PG metadata all cleaned up
- Celery Beat scheduling incremental sync every N hours
- All `test_worker/` and `test_scheduler/` tests GREEN (embed test `xfail` until Phase 5)
