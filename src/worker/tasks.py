import asyncio
from uuid import uuid4

import redis
import structlog
from celery import chain

from src.drive.drive_credentials import build_drive_service_for_sync_repo, effective_drive_folder_id
from src.drive.downloader import DriveDownloader
from src.drive.local_downloader import LocalFolderDownloader
from src.worker.celery_app import app, RetryableTask
from src.worker.task_helpers import (
    build_metadata_repo,
    build_settings,
    build_storage,
    derive_document_type,
)

logger = structlog.get_logger()

SYNC_LOCK_KEY = "rag:sync:lock"
SYNC_LOCK_TTL = 1800  # 30 minutes
MILVUS_INSERT_BATCH_SIZE = 1000


@app.task(bind=True, max_retries=1)
def run_incremental_sync(self):
    """Orchestrate: fetch changed files from Drive, dispatch per-file pipelines.

    Acquires a distributed lock to prevent concurrent syncs.
    """
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
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
        if settings.ingest_source == "drive" and settings.google_oauth_client_id:
            row = repo.get_drive_connection_sync()
            if row and row.refresh_token_enc and not row.selected_folder_id:
                task_logger.warning("sync.skipped", reason="OAuth connected but no folder selected")
                return

        downloader = _build_sync_downloader(settings, storage, repo)
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
    """Download a single file from configured source to MinIO."""
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=file_meta["id"], task="download_file")
    task_logger.info("task.started")

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        downloader = _build_sync_downloader(settings, storage, repo)
        minio_key = asyncio.run(downloader.download_file(file_meta))

        if minio_key is None:
            task_logger.info("task.skipped")
            return {"skipped": True, "drive_file_id": file_meta["id"]}

        repo.update_raw_key_sync(file_meta["id"], minio_key)
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
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
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
            repo.update_status_sync(
                drive_file_id,
                "skipped",
                error_message=f"Unsupported MIME: {download_result['mime_type']}",
            )
            task_logger.warning(
                "task.skipped",
                reason="unsupported mime type",
                mime_type=download_result["mime_type"],
            )
            return {"skipped": True, "drive_file_id": drive_file_id}

        text = converter.convert(raw_bytes, download_result["name"], download_result["mime_type"])

        text_key = f"{drive_file_id}.txt"
        storage.upload(settings.minio_bucket_text, text_key, text.encode("utf-8"))
        repo.update_text_key_sync(drive_file_id, text_key)
        repo.update_status_sync(drive_file_id, "converted")

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
    """Chunk text, embed via Ollama, upsert vectors to Milvus."""
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    drive_file_id = convert_result.get("drive_file_id", "unknown")
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=drive_file_id, task="embed_file")
    task_logger.info("task.started")

    if convert_result.get("skipped"):
        task_logger.info("task.skipped", reason="previous task skipped")
        return convert_result

    settings = build_settings()
    storage = build_storage(settings)

    try:
        text_bytes = storage.download(settings.minio_bucket_text, convert_result["minio_text_key"])
        text = text_bytes.decode("utf-8")

        from src.vectorizer.chunker import DocumentChunker

        chunker = DocumentChunker()
        chunks = chunker.chunk(
            text,
            source_file_id=drive_file_id,
            source_name=convert_result["name"],
            document_type=convert_result["document_type"],
        )

        if not chunks:
            task_logger.info("task.embed.no_chunks")
            asyncio.run(_update_embedded(settings, drive_file_id, chunk_count=0))
            return {"drive_file_id": drive_file_id, "chunk_count": 0}

        chunk_count = asyncio.run(_embed_and_store(settings, drive_file_id, chunks))
        task_logger.info("task.completed", chunk_count=chunk_count)
        return {"drive_file_id": drive_file_id, "chunk_count": chunk_count}
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise


async def _embed_and_store(settings, drive_file_id: str, chunks: list) -> int:
    """Single async context for all embedding + storage operations."""
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore

    embedder = BatchEmbedder(settings)
    texts = [c.text for c in chunks]
    embeddings = await embedder.embed_texts(texts)

    store = MilvusStore(settings)
    store.ensure_collection()
    store.delete_by_source(drive_file_id)

    chunk_dicts = [
        {
            "id": f"{c.source_file_id}_{c.chunk_index}",
            "source_file_id": c.source_file_id,
            "source_name": c.source_name,
            "document_type": c.document_type,
            "section_title": c.section_title,
            "chunk_index": c.chunk_index,
            "text": c.text,
        }
        for c in chunks
    ]
    store.upsert(chunk_dicts, embeddings)

    await _update_embedded(settings, drive_file_id, chunk_count=len(chunks))
    return len(chunks)


async def _update_embedded(settings, drive_file_id: str, chunk_count: int) -> None:
    """Update metadata: chunk_count, status, last_processed_at."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from src.metadata.repository import MetadataRepository

    engine = create_async_engine(settings.database_url.get_secret_value())
    async with AsyncSession(engine) as session:
        repo = MetadataRepository(session)
        await repo.update_chunk_count(drive_file_id, chunk_count)
        await repo.update_status(drive_file_id, "embedded")
        await repo.update_last_processed_at(drive_file_id)
        await session.commit()
    await engine.dispose()


@app.task(base=RetryableTask, bind=True)
def delete_file_vectors(self, drive_file_id: str) -> dict:
    """Remove vectors from Milvus, files from MinIO, and metadata from PostgreSQL."""
    from src.vectorizer.milvus_store import MilvusStore

    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
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

        repo.delete_file_record_sync(drive_file_id)
        task_logger.info("task.completed")
        return {"drive_file_id": drive_file_id, "deleted": True}
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


@app.task(base=RetryableTask, bind=True)
def restart_ingest(self) -> dict:
    """Clean previous ingestion artifacts, then queue a fresh incremental sync."""
    from src.vectorizer.milvus_store import MilvusStore

    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, task="restart_ingest")
    task_logger.info("task.started")

    settings = build_settings()
    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    vectors_removed = 0
    storage_deleted = 0
    storage_delete_failures = 0
    records_deleted = 0

    def _delete_object(bucket: str, key: str | None) -> None:
        nonlocal storage_deleted, storage_delete_failures
        if not key:
            return
        try:
            storage.delete(bucket, key)
            storage_deleted += 1
        except Exception as exc:  # best-effort cleanup
            storage_delete_failures += 1
            task_logger.debug("restart_ingest.storage_delete_failed", bucket=bucket, key=key, error=str(exc))

    try:
        store = MilvusStore(settings)
        records = repo.list_by_status(None)
        for record in records:
            drive_file_id = record.drive_file_id
            try:
                store.delete_by_source(drive_file_id)
                vectors_removed += 1
            except Exception as exc:  # best-effort cleanup
                task_logger.warning("restart_ingest.vector_delete_failed", drive_file_id=drive_file_id, error=str(exc))

            raw_candidates = [record.minio_raw_key, f"{drive_file_id}/{record.name}", drive_file_id]
            text_candidates = [record.minio_text_key, f"{drive_file_id}.txt"]
            for key in raw_candidates:
                _delete_object(settings.minio_bucket_raw, key)
            for key in text_candidates:
                _delete_object(settings.minio_bucket_text, key)

        records_deleted = len(records)
        repo.delete_all_file_records_sync()
        asyncio.run(repo.update_page_token(""))

        run_incremental_sync.delay(headers={"trace_id": trace_id})
        task_logger.info(
            "task.completed",
            vectors_removed=vectors_removed,
            storage_deleted=storage_deleted,
            storage_delete_failures=storage_delete_failures,
            records_deleted=records_deleted,
        )
        return {
            "status": "queued",
            "vectors_removed": vectors_removed,
            "storage_deleted": storage_deleted,
            "storage_delete_failures": storage_delete_failures,
            "records_deleted": records_deleted,
        }
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


@app.task(base=RetryableTask, bind=True)
def run_sql_generation(self, job_id: str, description: str, target_db: str) -> dict:
    """Long-running task to discover schema and extract data into SQL."""
    import redis
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from src.rag.retriever import Retriever
    from src.rag.llm_client import create_llm_client
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore
    from src.generator.sql_generator import SQLGenerator
    from src.generator.db_writer import DBWriter

    settings = build_settings()
    r = redis.Redis.from_url(settings.redis_cache_url)

    try:
        # Services
        embedder = BatchEmbedder(settings)
        vector_store = MilvusStore(settings)
        retriever = Retriever(embedder=embedder, vector_store=vector_store, cache=r)
        llm = create_llm_client(settings)
        sql_gen = SQLGenerator(retriever, llm)

        # 1. Discover Schema
        schema_sql = asyncio.run(sql_gen.discover_schema(description))
        r.hset(f"sql_job:{job_id}", "schema_sql", schema_sql)

        # 2. Retrieve chunks for data extraction
        chunks = asyncio.run(retriever.retrieve(description, top_k=50))

        # 3. Extract Data
        insert_statements = asyncio.run(sql_gen.extract_data(chunks, schema_sql))

        # 4. Write to DB
        # Use generated schema engine
        engine = create_async_engine(settings.database_url_generated.get_secret_value())

        async def _write():
            async with AsyncSession(engine) as session:
                writer = DBWriter(session)
                # First create table
                await writer.execute(schema_sql)
                # Then insert data
                return await writer.execute_many(insert_statements)

        count = asyncio.run(_write())
        asyncio.run(engine.dispose())

        r.hset(f"sql_job:{job_id}", mapping={"status": "completed", "insert_count": str(count)})
        return {"job_id": job_id, "status": "completed", "insert_count": count}

    except Exception as exc:
        logger.error("task.sql_gen.failed", job_id=job_id, error=str(exc))
        r.hset(f"sql_job:{job_id}", mapping={"status": "failed", "error": str(exc)})
        raise


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


def _build_sync_downloader(settings, storage, repo):
    if settings.ingest_source == "local":
        return LocalFolderDownloader(storage=storage, metadata_repo=repo, settings=settings)
    if settings.ingest_source == "drive":
        service = build_drive_service_for_sync_repo(settings, repo)
        folder_id = effective_drive_folder_id(settings, repo)
        return DriveDownloader(
            drive_service=service,
            storage=storage,
            metadata_repo=repo,
            settings=settings,
            drive_folder_id=folder_id,
        )
    raise ValueError(f"Unsupported ingest_source: {settings.ingest_source}")
