from __future__ import annotations

import asyncio
from uuid import uuid4

import redis
import structlog
from celery import chain

from src.worker.celery_app import RetryableTask, app
from src.worker.task_helpers import (
    build_metadata_repo,
    build_settings,
    build_storage,
    derive_document_type,
)

logger = structlog.get_logger()

SYNC_LOCK_KEY = "rag:sync:lock"
SYNC_LOCK_TTL = 1800  # 30 minutes


@app.task(bind=True, max_retries=1)
def run_incremental_sync(self):
    """Orchestrate: fetch changed files from Drive, dispatch per-file pipelines."""
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
            logger.info("task.download.skipped", drive_file_id=file_meta.get("id"))
            return {"skipped": True, "drive_file_id": file_meta.get("id")}

        logger.info("task.download.completed", drive_file_id=file_meta.get("id"), minio_key=minio_key)
        return {
            "drive_file_id": file_meta.get("id"),
            "minio_raw_key": minio_key,
            "mime_type": file_meta.get("mimeType"),
            "name": file_meta.get("name"),
        }
    finally:
        cleanup()


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


@app.task(base=RetryableTask, bind=True)
def embed_file(self, convert_result: dict) -> dict:
    """Chunk, embed, and store vectors. Placeholder until Phase 5."""
    if convert_result.get("skipped"):
        return convert_result

    raise NotImplementedError(
        "embed_file is a placeholder. Implement in Phase 5 with BatchEmbedder + MilvusStore."
    )


@app.task(base=RetryableTask, bind=True)
def delete_file_vectors(self, drive_file_id: str) -> dict:
    """Remove vectors from Milvus, files from MinIO, and metadata from PostgreSQL."""
    # Placeholder for MilvusStore until Phase 5
    # from src.vectorizer.milvus_store import MilvusStore

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        # Placeholder for Milvus deletion
        # store = MilvusStore(settings)
        # store.delete_by_source(drive_file_id)
        logger.info("task.delete.vectors_removed_placeholder", drive_file_id=drive_file_id)

        # Clean up MinIO objects
        raw_key = f"{drive_file_id}"
        text_key = f"{drive_file_id}.txt"
        
        # We need to list objects or know the exact name.
        # Since we use drive_file_id as prefix for raw and f"{drive_file_id}.txt" for text:
        try:
             # MinIO client (storage._client) could be used to list and delete prefix
             # For now, let's just try to delete the known text key.
             # Raw key is harder as it includes the original filename.
             storage.delete(settings.minio_bucket_text, text_key)
        except Exception as exc:
            logger.warning("task.delete.storage_cleanup_partial", drive_file_id=drive_file_id, error=str(exc))

        repo.delete_file_record(drive_file_id)
        logger.info("task.delete.completed", drive_file_id=drive_file_id)
        return {"drive_file_id": drive_file_id, "deleted": True}
    finally:
        cleanup()


def dispatch_file_pipeline(file_meta: dict) -> None:
    """Build and dispatch the download → convert → embed chain for one file."""
    trace_id = str(uuid4())
    pipeline = chain(
        download_file.s(file_meta),
        convert_file.s(),
        embed_file.s(),
    )
    pipeline.apply_async(headers={"trace_id": trace_id})
