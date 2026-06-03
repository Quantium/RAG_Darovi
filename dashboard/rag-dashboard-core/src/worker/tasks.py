import asyncio
import hashlib
import json
from uuid import uuid4

import redis
import structlog
from celery import chain

from src.converter.pdf_converter import PdfConverter
from src.drive.local_downloader import LocalFolderDownloader
from src.vision.circuit_breaker import CircuitBreaker
from src.vision.client import OpenAICompatVisionClient, VisionTimeoutError
from src.vision.extractor import VisionExtractor
from src.vision.image_utils import prepare_image
from src.vision.rasterizer import is_image_mime, rasterize_page
from src.vision.sentinels import VISION_SENTINEL_TEMPLATE, find_pages, has_sentinels
from src.worker.celery_app import app, RetryableTask, VisionRetryableTask
from src.worker.task_helpers import (
    build_metadata_repo,
    build_settings,
    build_storage,
    build_tenant_metadata_repo,
    derive_document_type,
)
from src.worker.tenant_runtime import (
    context_from_payload,
    is_vectorize_paused,
    read_active_tenants,
)

logger = structlog.get_logger()

SYNC_LOCK_KEY = "rag:sync:lock"
SYNC_LOCK_TTL = 1800  # 30 minutes
MILVUS_INSERT_BATCH_SIZE = 1000
VISION_DLQ_KEY = "vision:dlq"


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
    if not settings.legacy_ingest_pipeline_enabled:
        task_logger.info("sync.skipped_disabled", reason="legacy_ingest_pipeline_enabled=false")
        return
    r = redis.Redis.from_url(settings.redis_broker_url)

    if redis.Redis.from_url(settings.redis_cache_url).exists("rag:pause:ingest"):
        task_logger.info("sync.skipped_paused", reason="ingest paused")
        return

    if not r.set(SYNC_LOCK_KEY, "1", nx=True, ex=SYNC_LOCK_TTL):
        task_logger.warning("sync.skipped_concurrent", reason="Another sync is already running")
        return

    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        downloader = _build_sync_downloader(settings, storage, repo)
        changed_files, deleted_ids = asyncio.run(downloader.incremental_sync())
        task_logger.info("sync.files_found", changed=len(changed_files), deleted=len(deleted_ids))

        for file_meta in changed_files:
            dispatch_file_pipeline(file_meta, trace_id=trace_id)

        for drive_file_id in deleted_ids:
            # `headers` belongs to apply_async(), not the task signature. Celery
            # 5.6 validates kwargs against the function and would reject .delay().
            delete_file_vectors.apply_async(args=[drive_file_id], headers={"trace_id": trace_id})

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
    if redis.Redis.from_url(settings.redis_cache_url).exists("rag:pause:ingest"):
        task_logger.info("task.skipped", reason="ingest paused")
        return {"skipped": True, "drive_file_id": file_meta["id"]}

    storage = build_storage(settings)
    repo, cleanup = build_metadata_repo(settings)

    try:
        downloader = _build_sync_downloader(settings, storage, repo)
        minio_key = asyncio.run(downloader.download_file(file_meta))

        if minio_key is None:
            task_logger.info("task.skipped")
            return {"skipped": True, "drive_file_id": file_meta["id"]}

        repo.update_raw_key_sync(file_meta["id"], minio_key)
        repo.update_raw_stage_sync(
            file_meta["id"],
            minio_raw_key=minio_key,
            raw_source_version=file_meta.get("modifiedTime"),
            raw_status="synced",
        )
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
    if redis.Redis.from_url(settings.redis_cache_url).exists("rag:pause:transform"):
        task_logger.info("task.skipped", reason="transform paused")
        return {"skipped": True, "drive_file_id": drive_file_id}
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
        text_bytes = text.encode("utf-8")
        storage.upload(settings.minio_bucket_text, text_key, text_bytes)
        repo.update_text_key_sync(drive_file_id, text_key)
        repo.update_text_stage_sync(
            drive_file_id,
            minio_text_key=text_key,
            text_checksum=hashlib.sha256(text_bytes).hexdigest(),
            text_status="ready_for_embedding",
        )
        # If the converter left VLM sentinels, the file is NOT done yet — it
        # still needs the vision_extract task to transcribe scanned pages.
        # Use a distinct status so /status shows the real backlog instead of
        # claiming the file is "converted" while VISION_NEEDED tokens remain.
        next_status = "vision_pending" if has_sentinels(text) else "converted"
        repo.update_status_sync(drive_file_id, next_status)

        task_logger.info("task.completed", text_key=text_key)
        return {
            "drive_file_id": drive_file_id,
            "minio_text_key": text_key,
            "minio_raw_key": download_result["minio_raw_key"],
            "mime_type": download_result["mime_type"],
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
    tenant = context_from_payload(convert_result, settings)
    if is_vectorize_paused(redis.Redis.from_url(settings.redis_cache_url), tenant):
        task_logger.info("task.skipped", reason="vectorize paused", slug=tenant.slug)
        return {"skipped": True, "drive_file_id": drive_file_id}

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
            asyncio.run(_update_embedded(settings, drive_file_id, 0, tenant.schema_name))
            return {"drive_file_id": drive_file_id, "chunk_count": 0}

        kv_summary = convert_result.get("kv_summary") or {}
        if kv_summary:
            chunks = _prepend_kv_summary_to_first_chunk(chunks, kv_summary)

        chunk_count = asyncio.run(_embed_and_store(settings, drive_file_id, chunks, tenant))
        task_logger.info("task.completed", chunk_count=chunk_count, slug=tenant.slug)
        return {"drive_file_id": drive_file_id, "chunk_count": chunk_count}
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise


def _prepend_kv_summary_to_first_chunk(chunks: list, kv_summary: dict) -> list:
    """Inject a one-liner KV summary at the top of the first chunk.

    Improves semantic recall: queries that mention the issuer or amount
    will now match the chunk that also carries the surrounding context.
    Only fields that carry a non-null value are emitted to keep the
    summary line short and informative.
    """
    pairs = []
    for key in ("document_type", "issuer", "issued_at", "total_amount", "currency"):
        value = kv_summary.get(key)
        if value:
            pairs.append(f"{key}={value}")
    if not pairs:
        return chunks

    summary = "[document_summary] " + ", ".join(pairs) + "\n\n"
    first = chunks[0]
    first.text = summary + first.text
    return chunks


async def _embed_and_store(settings, drive_file_id: str, chunks: list, tenant) -> int:
    """Single async context for all embedding + storage operations.

    Vectors land in the licitación's Milvus collection (``tenant.collection``) and the
    metadata write-back targets the licitación's PostgreSQL schema (``tenant.schema_name``).
    """
    from src.vectorizer.embedder import BatchEmbedder
    from src.vectorizer.milvus_store import MilvusStore

    embedder = BatchEmbedder(settings)
    texts = [c.text for c in chunks]
    embeddings = await embedder.embed_texts(texts)

    store = MilvusStore(settings, collection_name=tenant.collection)
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

    await _update_embedded(settings, drive_file_id, len(chunks), tenant.schema_name)
    return len(chunks)


async def _update_embedded(settings, drive_file_id: str, chunk_count: int, schema_name: str) -> None:
    """Update metadata (chunk_count, status, last_processed_at) in the tenant schema."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.metadata.repository import MetadataRepository
    from src.tenant.engine import build_async_tenant_engine

    engine = build_async_tenant_engine(settings, schema_name)
    async with AsyncSession(engine) as session:
        repo = MetadataRepository(session)
        await repo.update_chunk_count(drive_file_id, chunk_count)
        await repo.update_status(drive_file_id, "embedded")
        await repo.update_text_stage(
            drive_file_id,
            text_status="embedded",
            text_error=None,
        )
        await repo.update_last_processed_at(drive_file_id)
        await session.commit()
    await engine.dispose()


@app.task(base=VisionRetryableTask, bind=True)
def vision_extract(self, convert_result: dict) -> dict:
    """Resolve VLM sentinels emitted by the converter step.

    No-op for born-digital documents. For pages flagged with the sentinel
    `\\u0000VISION_NEEDED:N\\u0000`, this task:

    1. Downloads the raw file and rasterizes the requested page.
    2. Calls VisionExtractor (Llama-3.2-Vision via Ollama) for OCR + KV.
    3. Substitutes the sentinel with the transcribed text.
    4. Re-uploads the patched text to MinIO and persists structured KV
       in Postgres (`extracted_documents` table).

    Failure handling (in order of preference):
      a) On VisionTimeoutError: retry once with a downscaled rasterization.
      b) Increment the Redis-backed circuit breaker on persistent errors.
         When the breaker opens, subsequent pages take the Tesseract
         fallback (when `vision_fallback_to_tesseract` is true), so the
         document still flows through embed_file with partial coverage.
      c) Pages that exhaust every strategy are replaced with a placeholder
         and pushed to the `vision:dlq` Redis list for human inspection.
    """
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    drive_file_id = convert_result.get("drive_file_id", "unknown")
    task_logger = logger.bind(trace_id=trace_id, drive_file_id=drive_file_id, task="vision_extract")
    task_logger.info("task.started")

    if convert_result.get("skipped"):
        task_logger.info("task.skipped", reason="previous task skipped")
        return convert_result

    settings = build_settings()
    tenant = context_from_payload(convert_result, settings)
    storage = build_storage(settings)
    repo, cleanup = build_tenant_metadata_repo(settings, tenant.schema_name)

    try:
        text_key = convert_result["minio_text_key"]
        text = storage.download(settings.minio_bucket_text, text_key).decode("utf-8")

        if not has_sentinels(text):
            task_logger.info("task.noop", reason="no_sentinels")
            return convert_result

        pages = find_pages(text)
        task_logger.info("task.pages_to_process", pages=pages)
        # Surfaces "in progress" in /status while the slow VLM pass runs.
        repo.update_status_sync(drive_file_id, "vision_processing")

        raw_bytes = storage.download(settings.minio_bucket_raw, convert_result["minio_raw_key"])
        mime_type = convert_result["mime_type"]

        redis_client = redis.Redis.from_url(settings.redis_cache_url)
        breaker = CircuitBreaker(
            redis_client,
            threshold=settings.vision_circuit_breaker_threshold,
            reset_after_s=settings.vision_circuit_breaker_reset_s,
        )
        client = OpenAICompatVisionClient(settings)
        extractor = VisionExtractor(client=client, settings=settings)
        tesseract_fallback = PdfConverter(settings) if settings.vision_fallback_to_tesseract else None

        aggregated_kv: dict[str, object] = {
            "document_type": None,
            "issuer": None,
            "issued_at": None,
            "total_amount": None,
            "currency": None,
            "parties": [],
            "extras": {},
        }

        for page_num in pages:
            sentinel = VISION_SENTINEL_TEMPLATE.format(page=page_num)
            replacement, page_kv = _resolve_sentinel(
                page_num=page_num,
                raw_bytes=raw_bytes,
                mime_type=mime_type,
                drive_file_id=drive_file_id,
                settings=settings,
                breaker=breaker,
                extractor=extractor,
                tesseract_fallback=tesseract_fallback,
                redis_client=redis_client,
                logger_=task_logger,
            )
            text = text.replace(sentinel, replacement, 1)
            if page_kv is not None:
                _merge_kv(aggregated_kv, page_kv)

        storage.upload(settings.minio_bucket_text, text_key, text.encode("utf-8"))

        repo.upsert_extracted_document_sync(
            drive_file_id,
            document_type=aggregated_kv.get("document_type"),
            issuer=aggregated_kv.get("issuer"),
            issued_at=aggregated_kv.get("issued_at"),
            total_amount=aggregated_kv.get("total_amount"),
            currency=aggregated_kv.get("currency"),
            parties=list(aggregated_kv.get("parties") or []),
            extras=dict(aggregated_kv.get("extras") or {}),
        )
        # VLM pass complete: text in MinIO has no sentinels left, so the file
        # is now equivalent to a regular "converted" doc and is safe for embed.
        repo.update_status_sync(drive_file_id, "converted")

        result = dict(convert_result)
        result["kv_summary"] = {
            "document_type": aggregated_kv.get("document_type"),
            "issuer": aggregated_kv.get("issuer"),
            "issued_at": (
                aggregated_kv["issued_at"].isoformat() if aggregated_kv.get("issued_at") else None
            ),
            "total_amount": (
                str(aggregated_kv["total_amount"]) if aggregated_kv.get("total_amount") else None
            ),
            "currency": aggregated_kv.get("currency"),
        }
        task_logger.info("task.completed", pages_processed=len(pages))
        return result
    except Exception as exc:
        task_logger.error("task.failed", error=str(exc))
        raise
    finally:
        cleanup()


def _resolve_sentinel(
    *,
    page_num: int,
    raw_bytes: bytes,
    mime_type: str,
    drive_file_id: str,
    settings,
    breaker,
    extractor,
    tesseract_fallback,
    redis_client,
    logger_,
) -> tuple[str, dict | None]:
    """Run the VLM (or fallback) for a single page. Returns (text, kv_dict|None)."""
    if not breaker.allow():
        logger_.warning("vision.cb.open_skipping", page=page_num)
        return _tesseract_fallback_text(
            tesseract_fallback, raw_bytes, mime_type, page_num, drive_file_id, redis_client, logger_
        ), None

    primary_dpi = settings.ocr_dpi
    downscale_dpi = settings.vision_downscale_dpi

    try:
        image_bytes = rasterize_page(raw_bytes, mime_type, page_num, dpi=primary_dpi)
        result = asyncio.run(extractor.extract(image_bytes))
        breaker.record_success()
        return result.text, _kv_to_dict(result.kv)
    except VisionTimeoutError as exc:
        logger_.warning("vision.timeout.retrying_with_downscale", page=page_num, error=str(exc))
        try:
            image_bytes = rasterize_page(raw_bytes, mime_type, page_num, dpi=downscale_dpi)
            # Tighter image budget on retry to mitigate OOM.
            tight = prepare_image(image_bytes, max_mb=max(1, settings.vision_max_image_mb // 2))
            result = asyncio.run(extractor.extract(tight))
            breaker.record_success()
            return result.text, _kv_to_dict(result.kv)
        except Exception as inner_exc:
            logger_.error("vision.downscale_retry_failed", page=page_num, error=str(inner_exc))
            breaker.record_failure()
            _push_to_dlq(redis_client, drive_file_id, page_num, f"timeout+downscale: {inner_exc}", logger_)
            return _tesseract_fallback_text(
                tesseract_fallback, raw_bytes, mime_type, page_num, drive_file_id, redis_client, logger_
            ), None
    except Exception as exc:
        logger_.error("vision.page_failed", page=page_num, error=str(exc))
        breaker.record_failure()
        _push_to_dlq(redis_client, drive_file_id, page_num, str(exc), logger_)
        return _tesseract_fallback_text(
            tesseract_fallback, raw_bytes, mime_type, page_num, drive_file_id, redis_client, logger_
        ), None


def _tesseract_fallback_text(
    tesseract_fallback,
    raw_bytes,
    mime_type,
    page_num,
    drive_file_id,
    redis_client,
    logger_,
) -> str:
    """Attempt Tesseract OCR as a fallback when the VLM is unavailable or fails.

    Pushes the failure to the dead-letter queue and returns a placeholder string
    if Tesseract is disabled or also fails.

    Args:
        tesseract_fallback: Configured Tesseract helper, or None if disabled.
        raw_bytes: Raw file content bytes.
        mime_type: MIME type of the file being processed.
        page_num: 1-based page number to OCR.
        drive_file_id: Unique identifier of the source file (for DLQ context).
        redis_client: Redis client for pushing DLQ entries.
        logger_: Bound structlog logger for this task invocation.

    Returns:
        OCR text string, or a '[OCR FAILED page N]' placeholder on total failure.
    """
    if tesseract_fallback is None:
        logger_.warning("vision.fallback_disabled", page=page_num)
        return f"[OCR FAILED page {page_num}]"

    try:
        if is_image_mime(mime_type):
            import io as _io

            from PIL import Image
            import pytesseract

            with Image.open(_io.BytesIO(raw_bytes)) as img:
                ocr_text = pytesseract.image_to_string(img)
        else:
            ocr_text = tesseract_fallback._ocr_page_tesseract(raw_bytes, page_num)
        if ocr_text and ocr_text.strip():
            return ocr_text
    except Exception as exc:
        logger_.error("vision.tesseract_fallback_failed", page=page_num, error=str(exc))
        _push_to_dlq(redis_client, drive_file_id, page_num, f"tesseract: {exc}", logger_)

    return f"[OCR FAILED page {page_num}]"


def _push_to_dlq(redis_client, drive_file_id: str, page: int, error: str, logger_) -> None:
    """Push a failed vision extraction entry to the Redis dead-letter queue.

    Args:
        redis_client: Redis client for the lpush operation.
        drive_file_id: Unique identifier of the file that failed.
        page: Page number that could not be OCR'd.
        error: Human-readable error description.
        logger_: Bound structlog logger for warning on DLQ push failure.
    """
    payload = json.dumps({"drive_file_id": drive_file_id, "page": page, "error": error})
    try:
        redis_client.lpush(VISION_DLQ_KEY, payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger_.error("vision.dlq_push_failed", error=str(exc))


def _kv_to_dict(kv) -> dict:
    """Serialize an ExtractedDocumentSchema to a plain dict for storage.

    Args:
        kv: An ExtractedDocumentSchema instance.

    Returns:
        Dict with document_type, issuer, issued_at, total_amount, currency, parties, and extras.
    """
    return {
        "document_type": kv.document_type,
        "issuer": kv.issuer,
        "issued_at": kv.issued_at,
        "total_amount": kv.total_amount,
        "currency": kv.currency,
        "parties": list(kv.parties),
        "extras": dict(kv.extras),
    }


def _merge_kv(aggregated: dict, page_kv: dict) -> None:
    """First non-empty value wins for fixed fields; lists/dicts are merged."""
    for key in ("document_type", "issuer", "issued_at", "total_amount", "currency"):
        if not aggregated.get(key) and page_kv.get(key):
            aggregated[key] = page_kv[key]

    parties = aggregated.setdefault("parties", [])
    for p in page_kv.get("parties", []):
        if p and p not in parties:
            parties.append(p)

    extras = aggregated.setdefault("extras", {})
    for k, v in page_kv.get("extras", {}).items():
        extras.setdefault(k, v)


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

        # See note above: pass `headers` via apply_async, not as a task kwarg.
        run_incremental_sync.apply_async(headers={"trace_id": trace_id})
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


@app.task(bind=True, max_retries=1)
def restart_vectorization(self) -> dict:
    """Drop Milvus vectors, reset embedding-related metadata, re-queue embedding poll."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from src.vectorizer.milvus_store import MilvusStore
    from src.worker.task_helpers import build_settings, ensure_milvus_collection

    settings = build_settings()
    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, task="restart_vectorization")
    task_logger.info("task.started")

    store = MilvusStore(settings)
    store.drop_collection_if_exists()
    ensure_milvus_collection(settings)

    engine = create_engine(settings.database_url_sync.get_secret_value())
    try:
        with Session(engine) as session:
            session.execute(
                text(
                    """
                    UPDATE file_records
                    SET
                      status = CASE WHEN status = 'embedded' THEN 'converted' ELSE status END,
                      chunk_count = 0,
                      last_processed_at = NULL,
                      text_status = CASE
                        WHEN text_status IN ('embedded', 'embedding_queued')
                          THEN 'ready_for_embedding'
                        ELSE text_status
                      END,
                      text_error = NULL
                    WHERE status = 'embedded'
                       OR text_status IN ('embedded', 'embedding_queued')
                       OR (text_status = 'ready_for_embedding' AND COALESCE(chunk_count, 0) > 0)
                    """
                )
            )
            session.commit()
    finally:
        engine.dispose()

    poll_text_ready_for_embedding.apply_async(headers={"trace_id": trace_id})
    task_logger.info("task.completed")
    return {"status": "queued_poll"}


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
    """Build and dispatch the download → convert → vision_extract → embed chain.

    `vision_extract` is a no-op for documents whose converters did not
    emit any VLM sentinels (born-digital PDFs, sheets, plain text, etc.),
    so the chain is safe to apply unconditionally.

    This legacy in-dashboard ingest path is single-tenant: the chain carries no
    licitación payload, so the downstream tasks default to the public schema and the
    global collection. Multi-tenant ingestion runs through the ingest_raw / extract_text
    services and the registry-driven poll tasks instead.
    """
    if trace_id is None:
        trace_id = str(uuid4())

    pipeline = chain(
        download_file.s(file_meta),
        convert_file.s(),
        vision_extract.s(),
        embed_file.s(),
    )
    pipeline.apply_async(headers={"trace_id": trace_id})


def dispatch_downstream_pipeline(convert_result: dict, trace_id: str | None = None) -> None:
    """Dispatch the downstream chain: vision extraction then embedding."""
    if trace_id is None:
        trace_id = str(uuid4())
    pipeline = chain(
        vision_extract.s(convert_result),
        embed_file.s(),
    )
    pipeline.apply_async(headers={"trace_id": trace_id})


@app.task(bind=True, max_retries=1)
def poll_text_ready_for_embedding(self):
    """Poll each active licitación for text-ready files and queue downstream processing.

    Iterates the registry; every licitación is swept inside its own PostgreSQL schema and
    its files are dispatched carrying the licitación context (slug / schema / collection) so
    embedding lands in the right schema and Milvus collection. One licitación's failure does
    not abort the others.
    """
    from sqlalchemy import create_engine

    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, task="poll_text_ready_for_embedding")

    settings = build_settings()
    redis_client = redis.Redis.from_url(settings.redis_cache_url)
    if redis_client.exists("rag:pause:vectorize"):
        task_logger.info("poll.skipped_paused", reason="vectorize paused (global)")
        return {"queued": 0, "skipped": 0}

    stale_threshold = settings.embedding_poll_interval_seconds * 6
    base_engine = create_engine(settings.database_url_sync.get_secret_value())
    queued = 0
    skipped = 0
    try:
        for tenant in read_active_tenants(base_engine, settings):
            if is_vectorize_paused(redis_client, tenant):
                task_logger.info("poll.tenant_skipped_paused", slug=tenant.slug)
                continue
            try:
                queued_t, skipped_t = _poll_tenant_text_ready(
                    settings, tenant, stale_threshold, trace_id, task_logger
                )
                queued += queued_t
                skipped += skipped_t
            except Exception as exc:  # isolate per-licitación failures
                task_logger.error("poll.tenant_failed", slug=tenant.slug, error=str(exc))
    finally:
        base_engine.dispose()

    task_logger.info("task.completed", queued=queued, skipped=skipped)
    return {"queued": queued, "skipped": skipped}


def _poll_tenant_text_ready(settings, tenant, stale_threshold, trace_id, task_logger):
    """Sweep one licitación's schema for text-ready files; returns (queued, skipped)."""
    repo, cleanup = build_tenant_metadata_repo(settings, tenant.schema_name)
    queued = 0
    try:
        stale_reset = repo.reset_stale_embedding_queued_sync(stale_threshold)
        if stale_reset:
            task_logger.warning(
                "poll.stale_embedding_queued_reset",
                slug=tenant.slug,
                count=stale_reset,
                threshold_seconds=stale_threshold,
            )

        skipped = repo.batch_fail_missing_text_key_sync()
        records = repo.batch_mark_embedding_queued_sync()
        for record in records:
            convert_result = {
                "drive_file_id": record["drive_file_id"],
                "minio_text_key": record["minio_text_key"],
                "minio_raw_key": record.get("minio_raw_key") or record["drive_file_id"],
                "mime_type": record["mime_type"],
                "name": record["name"],
                "document_type": derive_document_type(record["mime_type"]),
                **tenant.payload(),
            }
            dispatch_downstream_pipeline(convert_result, trace_id=trace_id)
            queued += 1
        return queued, skipped
    finally:
        cleanup()


@app.task(bind=True)
def poll_vision_pending(self):
    """Poll each active licitación for vision_pending files and dispatch vision+embed chains.

    Paused/archived licitaciones are excluded by the registry-status filter, so OCR is gated
    per licitación without any Redis dependency. One licitación's failure is isolated.
    """
    from sqlalchemy import create_engine

    headers: dict[str, str] = {}
    if hasattr(self, "request") and self.request:
        headers = self.request.get("headers") or {}
    trace_id = headers.get("trace_id", str(uuid4()))
    task_logger = logger.bind(trace_id=trace_id, task="poll_vision_pending")

    settings = build_settings()
    base_engine = create_engine(settings.database_url_sync.get_secret_value())
    queued = 0
    try:
        for tenant in read_active_tenants(base_engine, settings):
            try:
                queued += _poll_tenant_vision_pending(settings, tenant, trace_id)
            except Exception as exc:  # isolate per-licitación failures
                task_logger.error("poll.tenant_failed", slug=tenant.slug, error=str(exc))
    finally:
        base_engine.dispose()

    task_logger.info("task.completed", queued=queued)
    return {"queued": queued}


def _poll_tenant_vision_pending(settings, tenant, trace_id) -> int:
    """Dispatch vision+embed chains for one licitación's vision_pending files; returns count."""
    repo, cleanup = build_tenant_metadata_repo(settings, tenant.schema_name)
    queued = 0
    try:
        for record in repo.list_vision_pending_sync():
            if not record.minio_text_key or not record.minio_raw_key:
                continue
            convert_result = {
                "drive_file_id": record.drive_file_id,
                "minio_text_key": record.minio_text_key,
                "minio_raw_key": record.minio_raw_key,
                "mime_type": record.mime_type,
                "name": record.name,
                "document_type": derive_document_type(record.mime_type),
                **tenant.payload(),
            }
            repo.update_status_sync(record.drive_file_id, "vision_processing")
            chain(
                vision_extract.s(convert_result),
                embed_file.s(),
            ).apply_async(headers={"trace_id": trace_id})
            queued += 1
        return queued
    finally:
        cleanup()


def _build_sync_downloader(settings, storage, repo):
    """Construct the appropriate downloader based on the configured ingest source.

    Args:
        settings: Application settings providing ingest source configuration.
        storage: MinIOStorage instance for uploading raw files.
        repo: SyncMetadataRepository instance for updating file records.

    Returns:
        A LocalFolderDownloader (or other SourceDownloader) ready to sync files.
    """
    return LocalFolderDownloader(storage=storage, metadata_repo=repo, settings=settings)
