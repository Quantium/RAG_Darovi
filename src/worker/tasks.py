import asyncio
import structlog
import redis
from uuid import uuid4
from celery import chain

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

    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id)

    settings = build_settings()
    r = redis.Redis.from_url(settings.redis_broker_url)

    if not r.set(SYNC_LOCK_KEY, "1", nx=True, ex=SYNC_LOCK_TTL):
        task_logger.warning("sync.skipped_concurrent", reason="Another sync is already running")
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
        task_logger.info("sync.files_found", changed=len(changed_files), deleted=len(deleted_ids))

        for file_meta in changed_files:
            dispatch_file_pipeline(file_meta, trace_id=trace_id)

        for drive_file_id in deleted_ids:
            delete_file_vectors.delay(drive_file_id, headers={"trace_id": trace_id})

        task_logger.info("sync.dispatched", changed=len(changed_files), deleted=len(deleted_ids))
    finally:
        r.delete(SYNC_LOCK_KEY)
        cleanup()


@app.task(base=RetryableTask, bind=True)
def download_file(self, file_meta: dict) -> dict:
    """Download a single file from Drive to MinIO."""
    from src.drive.auth import build_drive_service
    from src.drive.downloader import DriveDownloader

    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=file_meta["id"], task="download_file")
    task_logger.info("task.started")

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
            task_logger.info("task.skipped")
            return {"skipped": True, "drive_file_id": file_meta["id"]}

        task_logger.info("task.completed", minio_key=minio_key)
        return {
            "drive_file_id": file_meta["id"],
            "minio_raw_key": minio_key,
            "mime_type": file_meta["mimeType"],
            "name": file_meta["name"],
        }
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


@app.task(base=RetryableTask, bind=True)
def convert_file(self, download_result: dict) -> dict:
    """Convert a raw file to plain text."""
    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    drive_file_id = download_result.get("drive_file_id", "unknown")
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=drive_file_id, task="convert_file")
    task_logger.info("task.started")

    if download_result.get("skipped"):
        task_logger.info("task.skipped", reason="previous task skipped")
        return download_result

    from src.converter import get_converter

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        raw_bytes = storage.download(settings.minio_bucket_raw, download_result["minio_raw_key"])
        try:
            converter = get_converter(download_result["mime_type"])
        except ValueError:
            repo.update_status(drive_file_id, "skipped", error_message=f"Unsupported MIME: {download_result['mime_type']}")
            task_logger.warning("task.skipped", reason="unsupported mime type", mime_type=download_result["mime_type"])
            return {"skipped": True, "drive_file_id": drive_file_id}

        text = converter.convert(raw_bytes, download_result["name"], download_result["mime_type"])

        text_key = f"{drive_file_id}.txt"
        storage.upload(settings.minio_bucket_text, text_key, text.encode("utf-8"))
        repo.update_status(drive_file_id, "converted")

        task_logger.info("task.completed", text_key=text_key)
        return {
            "drive_file_id": drive_file_id,
            "minio_text_key": text_key,
            "name": download_result["name"],
            "document_type": derive_document_type(download_result["mime_type"]),
        }
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


@app.task(base=RetryableTask, bind=True)
def embed_file(self, convert_result: dict) -> dict:
    """Chunk, embed, and store vectors. Placeholder until Phase 5."""
    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    drive_file_id = convert_result.get("drive_file_id", "unknown")
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=drive_file_id, task="embed_file")
    task_logger.info("task.started")

    if convert_result.get("skipped"):
        task_logger.info("task.skipped", reason="previous task skipped")
        return convert_result

    raise NotImplementedError(
        "embed_file is a placeholder. Implement in Phase 5 with BatchEmbedder + MilvusStore."
    )


@app.task(base=RetryableTask, bind=True)
def delete_file_vectors(self, drive_file_id: str) -> dict:
    """Remove vectors from Milvus, files from MinIO, and metadata from PostgreSQL."""
    from src.vectorizer.milvus_store import MilvusStore

    headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=drive_file_id, task="delete_file_vectors")
    task_logger.info("task.started")

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        store = MilvusStore(settings)
        store.delete_by_source(drive_file_id)
        task_logger.info("vectors.removed")

        # Clean up MinIO objects
        raw_key = f"{drive_file_id}"
        text_key = f"{drive_file_id}.txt"
        try:
            storage.delete(settings.minio_bucket_raw, raw_key)
            storage.delete(settings.minio_bucket_text, text_key)
        except Exception as exc:
            task_logger.warning("storage_cleanup.partial", error=str(exc))

        repo.delete_file_record(drive_file_id)
        task_logger.info("task.completed")
        return {"drive_file_id": drive_file_id, "deleted": True}
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


def dispatch_file_pipeline(file_meta: dict, trace_id: str | None = None) -> None:
    """Build and dispatch the download → convert → embed chain for one file."""
    if trace_id is None:
        trace_id = str(uuid4())

    pipeline = chain(
        download_file.s(file_meta),
        convert_file.s(),
        embed_file.s(),
    )
    pipeline.apply_async(headers={"trace_id": trace_id})
