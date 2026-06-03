"""Dashboard control panel API — pipeline metrics and destructive re-run triggers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from src.api.app import verify_api_key
from src.api.dashboard_schemas import DashboardActionResult, DashboardCardCounts, DashboardState, InFlightFile
from src.dashboard.processing_probe import ProcessingProbe
from src.ingest.source_counter import SourceCounter
from src.metadata.repository import LICITACION_STATUS_ACTIVE, LicitacionRepository, MetadataRepository
from src.rag.conversation import count_active_chat_sessions
from src.storage.backend import MinIOStorage
from src.tenant import tenant_session

logger = structlog.get_logger()

dashboard_router = APIRouter(tags=["dashboard"])

CONFIRM_HEADER = "X-Dashboard-Confirm"


def _require_dashboard_confirm(request: Request) -> None:
    """FastAPI dependency that blocks destructive actions unless the confirm header is set.

    Args:
        request: Incoming FastAPI request carrying the confirmation header.

    Raises:
        HTTPException: 400 if the X-Dashboard-Confirm header is not 'yes'.
    """
    val = request.headers.get(CONFIRM_HEADER, "").strip().lower()
    if val != "yes":
        raise HTTPException(
            status_code=400,
            detail=f"Destructive action requires header {CONFIRM_HEADER}: yes",
        )


@dataclass(frozen=True)
class DashboardTenant:
    """Resolved licitación scope for a dashboard snapshot."""

    slug: str
    schema_name: str
    collection: str
    source_path: str

    @property
    def key_prefix(self) -> str:
        """MinIO key prefix: empty for the public tenant, '<slug>/' otherwise."""
        return "" if self.schema_name == "public" else f"{self.slug}/"


def _tenant_from_row(row) -> DashboardTenant:
    return DashboardTenant(
        slug=row.slug,
        schema_name=row.schema_name,
        collection=row.milvus_collection,
        source_path=row.source_path or "",
    )


async def _resolve_dashboard_tenant(request: Request, slug: str | None) -> DashboardTenant:
    """Resolve the licitación a dashboard snapshot is scoped to.

    With a slug, returns that licitación if it is not archived (admins may inspect a paused
    one); 404 otherwise. Without a slug, returns the first active licitación, falling back to
    the first non-archived one, or — if the registry is empty — a legacy public default
    (public schema, global collection, whole source root). Archived licitaciones are never
    selectable.

    Raises:
        HTTPException: 404 when an explicit slug matches no selectable licitación.
    """
    settings: Settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        rows = await LicitacionRepository(session).list_all(include_archived=False)
    if slug:
        for row in rows:
            if row.slug == slug:
                return _tenant_from_row(row)
        raise HTTPException(status_code=404, detail="unknown or inactive licitación")
    if rows:
        active = [r for r in rows if r.status == LICITACION_STATUS_ACTIVE]
        return _tenant_from_row(active[0] if active else rows[0])
    return DashboardTenant(slug="", schema_name="public", collection=settings.milvus_collection, source_path="")


async def _scoped_pg_counts(engine, schema_name: str, probe: ProcessingProbe):
    """Gather the PostgreSQL-side dashboard aggregates inside the licitación schema."""
    async with tenant_session(engine, schema_name) as session:
        repo = MetadataRepository(session)
        pg = await repo.get_dashboard_counts()
        inflight = await repo.get_inflight_files()
        extract_lock = await probe.advisory_extract_lock_held(session)
        recent_raw = await probe.max_raw_synced_recent(session)
    return pg, inflight, extract_lock, recent_raw


def _count_vectors(request: Request, collection: str) -> int:
    """Count Milvus entities for a licitación collection, reusing app state for the default one."""
    settings: Settings = request.app.state.settings
    if collection == settings.milvus_collection:
        return request.app.state.vector_store.count_entities()
    from src.vectorizer.milvus_store import MilvusStore

    return MilvusStore(settings, collection_name=collection).count_entities()


@dashboard_router.get(
    "/dashboard/state",
    response_model=DashboardState,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_state(request: Request, licitacion: str | None = None) -> DashboardState:
    """Build and return the full dashboard state snapshot for one licitación.

    Aggregates counts from PostgreSQL, MinIO, Milvus, Redis, Celery, and the source adapter,
    all scoped to the selected licitación (its schema, collection, MinIO prefix, and source
    subfolder). Defaults to the first active licitación when ``licitacion`` is omitted.

    Args:
        request: Incoming FastAPI request carrying app state.
        licitacion: Optional licitación slug to scope the snapshot to.

    Returns:
        DashboardState with card counts, processing flags, pause state, and in-flight files.
    """
    settings: Settings = request.app.state.settings
    tenant = await _resolve_dashboard_tenant(request, licitacion)
    storage = MinIOStorage(settings)
    raw_bucket = settings.minio_bucket_raw
    text_bucket = settings.minio_bucket_text

    minio_raw_total = storage.count_objects(raw_bucket, prefix=tenant.key_prefix)
    minio_text_total = storage.count_objects(text_bucket, prefix=tenant.key_prefix)

    source_total, source_url = SourceCounter(settings).count(sub_path=tenant.source_path)

    redis_client = request.app.state.redis_cache
    sessions_legacy, sessions_chatbot = count_active_chat_sessions(redis_client)

    probe = ProcessingProbe(settings)
    celery_ingest, celery_vector, active_embed_args = probe.celery_flags()

    pg, inflight, extract_lock, recent_raw = await _scoped_pg_counts(
        request.app.state.engine, tenant.schema_name, probe
    )

    milvus_vectors = _count_vectors(request, tenant.collection)

    postgres_total = pg["postgres_total"]
    source_n = source_total if source_total is not None else postgres_total
    postgres_missing = max(0, source_n - postgres_total)

    ingest_processing = celery_ingest or recent_raw
    transform_processing = extract_lock or pg["text_processing_now"] > 0 or pg["vision_processing_files"] > 0
    vectorize_processing = celery_vector

    cards = DashboardCardCounts(
        source_total=source_total,
        minio_raw_total=minio_raw_total,
        minio_text_total=minio_text_total,
        raw_pending=pg["raw_pending"],
        raw_synced=pg["raw_synced"],
        transform_total=pg["transform_total"],
        transform_done=pg["transform_done"],
        text_ready=pg["text_ready"],
        text_pending=pg["text_pending"],
        text_failed=pg["text_failed"],
        text_processing_now=pg["text_processing_now"],
        postgres_total=postgres_total,
        postgres_missing=postgres_missing,
        postgres_to_reprocess=pg["postgres_to_reprocess"],
        milvus_vectors=milvus_vectors,
        milvus_files_vectorized=pg["milvus_files_vectorized"],
        milvus_pending_files=pg["milvus_pending_files"],
        vision_pending_files=pg["vision_pending_files"],
        vision_processing_files=pg["vision_processing_files"],
        sessions_legacy=sessions_legacy,
        sessions_chatbot_v2=sessions_chatbot,
    )

    transform_inf = inflight.get("transform")
    # Prefer the live Celery task args (exact file being embedded) over the DB snapshot
    milvus_inf = active_embed_args or inflight.get("milvus")

    transform_inflight_file = (
        InFlightFile(
            name=transform_inf["name"],
            drive_file_id=transform_inf["drive_file_id"],
            minio_key=transform_inf.get("minio_raw_key") or "",
            minio_bucket=settings.minio_bucket_raw,
        )
        if transform_inf
        else None
    )
    milvus_inflight_file = (
        InFlightFile(
            name=milvus_inf["name"],
            drive_file_id=milvus_inf["drive_file_id"],
            minio_key=milvus_inf.get("minio_text_key") or "",
            minio_bucket=settings.minio_bucket_text,
        )
        if milvus_inf
        else None
    )

    r = request.app.state.redis_cache
    ingest_paused = bool(r.exists("rag:pause:ingest"))
    transform_paused = bool(r.exists("rag:pause:transform"))
    vectorize_paused = bool(r.exists("rag:pause:vectorize"))

    if ingest_paused:
        ingest_processing = False
    if transform_paused:
        transform_processing = False
    if vectorize_paused:
        vectorize_processing = False

    return DashboardState(
        cards=cards,
        source_url=source_url,
        selected_licitacion=tenant.slug or None,
        ingest_processing=ingest_processing,
        transform_processing=transform_processing,
        vectorize_processing=vectorize_processing,
        ingest_paused=ingest_paused,
        transform_paused=transform_paused,
        vectorize_paused=vectorize_paused,
        transform_inflight_file=transform_inflight_file,
        milvus_inflight_file=milvus_inflight_file,
        updated_at=datetime.now(timezone.utc),
    )


async def _reset_all_raw_stage(session: AsyncSession) -> None:
    """Reset every file_record back to a clean 'pending' state, clearing all stage columns.

    Args:
        session: Active SQLAlchemy async session to execute the update on.
    """
    await session.execute(
        text(
            """
            UPDATE file_records SET
                raw_status = 'pending',
                raw_checksum = NULL,
                raw_source_version = NULL,
                raw_synced_at = NULL,
                minio_raw_key = NULL,
                text_status = 'pending',
                text_source_checksum = NULL,
                text_checksum = NULL,
                text_extracted_at = NULL,
                minio_text_key = NULL,
                text_error = NULL,
                status = 'pending',
                chunk_count = 0,
                last_processed_at = NULL,
                error_message = NULL
            """
        )
    )
    await session.commit()


@dashboard_router.post(
    "/dashboard/re-ingest",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_re_ingest(request: Request) -> DashboardActionResult:
    """Clear all raw MinIO objects, reset file records, and queue a full re-ingestion.

    Requires the X-Dashboard-Confirm: yes header. Also triggers the ingest-raw HTTP service
    if INGEST_RAW_TRIGGER_URL is configured.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult describing how many objects were cleared and the trigger outcome.
    """
    settings: Settings = request.app.state.settings
    storage = MinIOStorage(settings)
    n = storage.remove_all_objects(settings.minio_bucket_raw)

    async with AsyncSession(request.app.state.engine) as session:
        await _reset_all_raw_stage(session)

    from src.worker.tasks import run_incremental_sync

    job = run_incremental_sync.delay()
    job_ids = [str(job.id)] if job and job.id else []

    trigger_ok = False
    base = (settings.ingest_raw_trigger_url or "").strip()
    if base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base.rstrip('/')}/trigger/run")
                trigger_ok = r.is_success
        except Exception as exc:
            logger.warning("dashboard.re_ingest_trigger_failed", error=str(exc))

    detail = f"Cleared {n} RAW object(s); queued incremental sync."
    if base:
        detail += " Ingest-raw trigger: " + ("ok" if trigger_ok else "failed or unreachable")

    return DashboardActionResult(status="queued", detail=detail, job_ids=job_ids)


async def _reset_text_for_raw_synced(session: AsyncSession) -> None:
    """Reset text-stage columns for all rows that already have raw_status='synced'.

    Args:
        session: Active SQLAlchemy async session to execute the update on.
    """
    await session.execute(
        text(
            """
            UPDATE file_records SET
                text_status = 'pending',
                text_source_checksum = NULL,
                text_checksum = NULL,
                text_extracted_at = NULL,
                minio_text_key = NULL,
                text_error = NULL,
                status = 'downloaded',
                chunk_count = 0,
                last_processed_at = NULL
            WHERE raw_status = 'synced'
            """
        )
    )
    await session.commit()


@dashboard_router.post(
    "/dashboard/trigger-transform",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_trigger_transform(request: Request) -> DashboardActionResult:
    """Fire the extract-text service without clearing any data."""
    settings: Settings = request.app.state.settings
    base = (settings.extract_text_trigger_url or "").strip()
    if not base:
        return DashboardActionResult(status="skipped", detail="EXTRACT_TEXT_TRIGGER_URL not configured.", job_ids=[])
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{base.rstrip('/')}/trigger/run")
            r.raise_for_status()
            payload = r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"extract-text trigger failed: {exc}") from exc

    detail = f"Triggered. Result: {payload}"
    return DashboardActionResult(status="ok", detail=detail, job_ids=[])


@dashboard_router.post(
    "/dashboard/re-transform",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_re_transform(request: Request) -> DashboardActionResult:
    """Clear all text MinIO objects, reset text stage for raw-synced rows, and trigger extract-text.

    Requires the X-Dashboard-Confirm: yes header.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult describing cleared objects and the trigger outcome.
    """
    settings: Settings = request.app.state.settings
    storage = MinIOStorage(settings)
    n = storage.remove_all_objects(settings.minio_bucket_text)

    async with AsyncSession(request.app.state.engine) as session:
        await _reset_text_for_raw_synced(session)

    trigger_ok = False
    base = (settings.extract_text_trigger_url or "").strip()
    if base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base.rstrip('/')}/trigger/run")
                trigger_ok = r.is_success
        except Exception as exc:
            logger.warning("dashboard.re_transform_trigger_failed", error=str(exc))

    detail = f"Cleared {n} TEXT object(s); reset text stage for raw-synced rows."
    if base:
        detail += " Extract-text trigger: " + ("ok" if trigger_ok else "failed or unreachable")

    return DashboardActionResult(status="queued", detail=detail, job_ids=[])


@dashboard_router.post(
    "/dashboard/re-vectorize",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_re_vectorize(request: Request) -> DashboardActionResult:
    """Drop and recreate the Milvus collection, then queue a re-embedding pass via Celery.

    Requires the X-Dashboard-Confirm: yes header.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult with the queued Celery job ID.
    """
    from src.worker.tasks import restart_vectorization

    job = restart_vectorization.delay()
    job_ids = [str(job.id)] if job and job.id else []
    return DashboardActionResult(
        status="queued",
        detail="Vector collection reset and embedding poll queued (Celery).",
        job_ids=job_ids,
    )


@dashboard_router.post(
    "/dashboard/clear-data",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_clear_data(request: Request) -> DashboardActionResult:
    """Clear Redis conversation/cache keys and drop all Milvus vectors."""
    redis_client = request.app.state.redis_cache

    deleted_redis = 0
    for pattern in ("conv:*", "chatbot:conv:*", "ra-retrieval:*"):
        keys = list(redis_client.scan_iter(match=pattern, count=500))
        if keys:
            deleted_redis += redis_client.delete(*keys)

    vector_store = request.app.state.vector_store
    deleted_vectors = vector_store.count_entities()
    vector_store.drop_collection_if_exists()
    vector_store.ensure_collection()

    logger.info("dashboard.clear_data", deleted_redis=deleted_redis, deleted_vectors=deleted_vectors)
    return DashboardActionResult(
        status="ok",
        detail=f"Cleared {deleted_redis} Redis keys and {deleted_vectors} Milvus vectors.",
        job_ids=[],
    )


@dashboard_router.post(
    "/dashboard/erase-all",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_erase_all(request: Request) -> DashboardActionResult:
    """Delete everything: Postgres records, MinIO objects, Milvus vectors, Redis keys."""
    settings: Settings = request.app.state.settings

    # Redis
    redis_client = request.app.state.redis_cache
    deleted_redis = 0
    for pattern in ("conv:*", "chatbot:conv:*", "ra-retrieval:*"):
        keys = list(redis_client.scan_iter(match=pattern, count=500))
        if keys:
            deleted_redis += redis_client.delete(*keys)

    # Milvus
    vector_store = request.app.state.vector_store
    deleted_vectors = vector_store.count_entities()
    vector_store.drop_collection_if_exists()
    vector_store.ensure_collection()

    # MinIO
    storage = MinIOStorage(settings)
    raw_cleared = storage.remove_all_objects(settings.minio_bucket_raw)
    text_cleared = storage.remove_all_objects(settings.minio_bucket_text)

    # Postgres — delete all file records (extracted_documents cascades) and sync state
    async with AsyncSession(request.app.state.engine) as session:
        await session.execute(text("DELETE FROM extracted_documents"))
        result = await session.execute(text("DELETE FROM file_records"))
        deleted_rows = result.rowcount
        await session.execute(text("DELETE FROM sync_state"))
        await session.commit()

    logger.info(
        "dashboard.erase_all",
        deleted_redis=deleted_redis,
        deleted_vectors=deleted_vectors,
        raw_cleared=raw_cleared,
        text_cleared=text_cleared,
        deleted_rows=deleted_rows,
    )
    return DashboardActionResult(
        status="ok",
        detail=(
            f"Erased {deleted_rows} Postgres rows, {raw_cleared} RAW + {text_cleared} TEXT MinIO objects, "
            f"{deleted_vectors} Milvus vectors, {deleted_redis} Redis keys."
        ),
        job_ids=[],
    )


@dashboard_router.post(
    "/dashboard/ingest_pause",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_ingest_pause(request: Request) -> DashboardActionResult:
    """Set the Redis pause flag for the ingest pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was paused.
    """
    request.app.state.redis_cache.set("rag:pause:ingest", "1")
    logger.info("dashboard.pause", stage="ingest")
    return DashboardActionResult(status="ok", detail="Ingest pipeline paused.", job_ids=[])


@dashboard_router.post(
    "/dashboard/ingest_resume",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_ingest_resume(request: Request) -> DashboardActionResult:
    """Clear the Redis pause flag for the ingest pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was resumed.
    """
    request.app.state.redis_cache.delete("rag:pause:ingest")
    logger.info("dashboard.resume", stage="ingest")
    return DashboardActionResult(status="ok", detail="Ingest pipeline resumed.", job_ids=[])


@dashboard_router.post(
    "/dashboard/transform_pause",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_transform_pause(request: Request) -> DashboardActionResult:
    """Set the Redis pause flag for the transform pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was paused.
    """
    request.app.state.redis_cache.set("rag:pause:transform", "1")
    logger.info("dashboard.pause", stage="transform")
    return DashboardActionResult(status="ok", detail="Transform pipeline paused.", job_ids=[])


@dashboard_router.post(
    "/dashboard/transform_resume",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_transform_resume(request: Request) -> DashboardActionResult:
    """Clear the Redis pause flag for the transform pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was resumed.
    """
    request.app.state.redis_cache.delete("rag:pause:transform")
    logger.info("dashboard.resume", stage="transform")
    return DashboardActionResult(status="ok", detail="Transform pipeline resumed.", job_ids=[])


@dashboard_router.post(
    "/dashboard/vectorize_pause",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_vectorize_pause(request: Request) -> DashboardActionResult:
    """Set the Redis pause flag for the vectorize pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was paused.
    """
    request.app.state.redis_cache.set("rag:pause:vectorize", "1")
    logger.info("dashboard.pause", stage="vectorize")
    return DashboardActionResult(status="ok", detail="Vectorize pipeline paused.", job_ids=[])


@dashboard_router.post(
    "/dashboard/vectorize_resume",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key)],
)
async def dashboard_vectorize_resume(request: Request) -> DashboardActionResult:
    """Clear the Redis pause flag for the vectorize pipeline stage.

    Args:
        request: Incoming FastAPI request carrying app state.

    Returns:
        DashboardActionResult confirming the stage was resumed.
    """
    request.app.state.redis_cache.delete("rag:pause:vectorize")
    logger.info("dashboard.resume", stage="vectorize")
    return DashboardActionResult(status="ok", detail="Vectorize pipeline resumed.", job_ids=[])
