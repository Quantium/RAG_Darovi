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


async def _resolve_destructive_tenant(
    request: Request, licitacion: str | None
) -> tuple[DashboardTenant, tuple[str, ...]]:
    """Resolve the licitación a destructive action targets, with a cross-tenant guard.

    Destructive actions must never fall back to a global scope. Whenever the registry holds
    any rows, an explicit, selectable ``licitacion`` is required (400 otherwise) so a stray
    click can only ever affect a single tenant. Returns the resolved tenant plus the
    ``<slug>/`` MinIO prefixes owned by *other* licitaciones — non-empty only for the public
    tenant, whose flat key space would otherwise include them — to pass as ``exclude_prefixes``.
    """
    async with AsyncSession(request.app.state.engine) as session:
        rows = await LicitacionRepository(session).list_all(include_archived=False)
    if rows and not licitacion:
        raise HTTPException(status_code=400, detail="licitación is required for destructive actions")
    tenant = await _resolve_dashboard_tenant(request, licitacion)
    others = tuple(f"{r.slug}/" for r in rows if r.schema_name != "public" and r.slug != tenant.slug)
    exclude = others if tenant.schema_name == "public" else ()
    return tenant, exclude


async def _reset_in_tenant(request: Request, schema_name: str, reset_fn) -> None:
    """Run an async file_records reset helper inside one licitación schema.

    Uses a connection-level ``search_path`` engine (Neon direct endpoint) so the helper's
    bare-table UPDATE and its own COMMIT resolve to the tenant schema, never ``public``.
    """
    from src.tenant.engine import build_async_tenant_engine

    engine = build_async_tenant_engine(request.app.state.settings, schema_name)
    try:
        async with AsyncSession(engine) as session:
            await reset_fn(session)
    finally:
        await engine.dispose()


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


def _tenant_vector_store(request: Request, collection: str):
    """Return a MilvusStore for a licitación collection, reusing app state for the default one."""
    settings: Settings = request.app.state.settings
    if collection == settings.milvus_collection:
        return request.app.state.vector_store
    from src.vectorizer.milvus_store import MilvusStore

    return MilvusStore(settings, collection_name=collection)


def _clear_tenant_redis(redis_client, tenant: DashboardTenant, other_slugs: tuple[str, ...]) -> int:
    """Delete one licitación's conversation history and flush the shared retrieval cache.

    Conversation history is per-tenant data, so only this licitación's keys are removed:
    ``chatbot:conv:<slug>:*`` for a real tenant; the un-prefixed legacy ``conv:*`` /
    ``chatbot:conv:*`` for the public tenant, explicitly skipping any other tenant's
    ``chatbot:conv:<slug>:`` keys. The retrieval cache (``ra-retrieval:*``) holds no tenant
    data (TTL'd query results), so it is flushed wholesale to avoid serving results for
    just-dropped vectors.
    """

    def _as_str(k) -> str:
        return k.decode() if isinstance(k, (bytes, bytearray)) else k

    deleted = 0
    if tenant.slug:
        keys = list(redis_client.scan_iter(match=f"chatbot:conv:{tenant.slug}:*", count=500))
        if keys:
            deleted += redis_client.delete(*keys)
    else:
        protect = tuple(f"chatbot:conv:{s}:" for s in other_slugs)
        for pattern in ("conv:*", "chatbot:conv:*"):
            keys = [
                k for k in redis_client.scan_iter(match=pattern, count=500)
                if not _as_str(k).startswith(protect)
            ]
            if keys:
                deleted += redis_client.delete(*keys)
    cache_keys = list(redis_client.scan_iter(match="ra-retrieval:*", count=500))
    if cache_keys:
        deleted += redis_client.delete(*cache_keys)
    return deleted


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
async def dashboard_re_ingest(request: Request, licitacion: str | None = None) -> DashboardActionResult:
    """Clear ONE licitación's raw MinIO objects, reset its file records, and re-ingest it.

    Scoped to the selected licitación: removes only its ``<slug>/`` RAW objects (never another
    tenant's keys) and resets file_records inside its schema. Requires the X-Dashboard-Confirm:
    yes header and — whenever any licitación exists — an explicit ``licitacion``. Re-ingestion
    is delegated to the ingest-raw service, which is per-tenant and idempotent: it re-uploads
    this licitación's cleared files from source and skips every other tenant (unchanged).

    Args:
        request: Incoming FastAPI request carrying app state.
        licitacion: Slug of the licitación to re-ingest.

    Returns:
        DashboardActionResult describing how many objects were cleared and the trigger outcome.
    """
    settings: Settings = request.app.state.settings
    tenant, exclude = await _resolve_destructive_tenant(request, licitacion)
    storage = MinIOStorage(settings)
    n = storage.remove_objects(
        settings.minio_bucket_raw, prefix=tenant.key_prefix, exclude_prefixes=exclude
    )

    await _reset_in_tenant(request, tenant.schema_name, _reset_all_raw_stage)

    trigger_ok = False
    base = (settings.ingest_raw_trigger_url or "").strip()
    if base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base.rstrip('/')}/trigger/run")
                trigger_ok = r.is_success
        except Exception as exc:
            logger.warning("dashboard.re_ingest_trigger_failed", error=str(exc))

    detail = f"Cleared {n} RAW object(s) for '{tenant.slug or 'public'}'; reset raw stage."
    if base:
        detail += " Ingest-raw trigger: " + ("ok" if trigger_ok else "failed or unreachable")

    return DashboardActionResult(status="queued", detail=detail, job_ids=[])


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
async def dashboard_re_transform(request: Request, licitacion: str | None = None) -> DashboardActionResult:
    """Clear ONE licitación's text MinIO objects, reset its text stage, and trigger extract-text.

    Scoped to the selected licitación: removes only its ``<slug>/`` TEXT objects and resets the
    text stage for its raw-synced rows inside its schema. Requires the X-Dashboard-Confirm: yes
    header and — whenever any licitación exists — an explicit ``licitacion``. The extract-text
    service is per-tenant and idempotent, so it re-extracts only this licitación.

    Args:
        request: Incoming FastAPI request carrying app state.
        licitacion: Slug of the licitación to re-transform.

    Returns:
        DashboardActionResult describing cleared objects and the trigger outcome.
    """
    settings: Settings = request.app.state.settings
    tenant, exclude = await _resolve_destructive_tenant(request, licitacion)
    storage = MinIOStorage(settings)
    n = storage.remove_objects(
        settings.minio_bucket_text, prefix=tenant.key_prefix, exclude_prefixes=exclude
    )

    await _reset_in_tenant(request, tenant.schema_name, _reset_text_for_raw_synced)

    trigger_ok = False
    base = (settings.extract_text_trigger_url or "").strip()
    if base:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{base.rstrip('/')}/trigger/run")
                trigger_ok = r.is_success
        except Exception as exc:
            logger.warning("dashboard.re_transform_trigger_failed", error=str(exc))

    detail = f"Cleared {n} TEXT object(s) for '{tenant.slug or 'public'}'; reset text stage."
    if base:
        detail += " Extract-text trigger: " + ("ok" if trigger_ok else "failed or unreachable")

    return DashboardActionResult(status="queued", detail=detail, job_ids=[])


@dashboard_router.post(
    "/dashboard/re-vectorize",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_re_vectorize(request: Request, licitacion: str | None = None) -> DashboardActionResult:
    """Drop and recreate ONE licitación's Milvus collection, then re-embed only that tenant.

    Scoped to the selected licitación: resets the ``rag_<slug>`` collection and the embedding
    state inside its schema. Requires the X-Dashboard-Confirm: yes header and — whenever any
    licitación exists — an explicit ``licitacion``.

    Args:
        request: Incoming FastAPI request carrying app state.
        licitacion: Slug of the licitación to re-vectorize.

    Returns:
        DashboardActionResult with the queued Celery job ID.
    """
    from src.worker.tasks import restart_vectorization

    tenant, _ = await _resolve_destructive_tenant(request, licitacion)
    job = restart_vectorization.delay(
        slug=tenant.slug, schema_name=tenant.schema_name, collection=tenant.collection
    )
    job_ids = [str(job.id)] if job and job.id else []
    return DashboardActionResult(
        status="queued",
        detail=f"Vector collection reset and re-embedding queued for '{tenant.slug or 'public'}'.",
        job_ids=job_ids,
    )


@dashboard_router.post(
    "/dashboard/clear-data",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_clear_data(request: Request, licitacion: str | None = None) -> DashboardActionResult:
    """Drop ONE licitación's Milvus vectors and clear its conversation history.

    Scoped to the selected licitación: drops/recreates its ``rag_<slug>`` collection and removes
    only its conversation keys (other tenants' history is preserved). Requires the
    X-Dashboard-Confirm: yes header and — whenever any licitación exists — an explicit ``licitacion``.
    """
    tenant, exclude = await _resolve_destructive_tenant(request, licitacion)
    other_slugs = tuple(p.rstrip("/") for p in exclude)

    redis_client = request.app.state.redis_cache
    deleted_redis = _clear_tenant_redis(redis_client, tenant, other_slugs)

    store = _tenant_vector_store(request, tenant.collection)
    deleted_vectors = store.count_entities()
    store.drop_collection_if_exists()
    store.ensure_collection()

    logger.info(
        "dashboard.clear_data",
        slug=tenant.slug or "public",
        deleted_redis=deleted_redis,
        deleted_vectors=deleted_vectors,
    )
    return DashboardActionResult(
        status="ok",
        detail=f"Cleared {deleted_redis} Redis keys and {deleted_vectors} Milvus vectors for '{tenant.slug or 'public'}'.",
        job_ids=[],
    )


@dashboard_router.post(
    "/dashboard/erase-all",
    response_model=DashboardActionResult,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def dashboard_erase_all(request: Request, licitacion: str | None = None) -> DashboardActionResult:
    """Delete ONE licitación's data: its Postgres rows, MinIO objects, Milvus vectors, Redis keys.

    Scoped to the selected licitación: Milvus ``rag_<slug>`` collection, ``<slug>/`` MinIO objects
    in both buckets (never another tenant's keys), file_records/sync_state inside its schema, and
    its conversation history. Requires the X-Dashboard-Confirm: yes header and — whenever any
    licitación exists — an explicit ``licitacion``.
    """
    settings: Settings = request.app.state.settings
    tenant, exclude = await _resolve_destructive_tenant(request, licitacion)
    other_slugs = tuple(p.rstrip("/") for p in exclude)

    # Redis — this licitación's conversation history only
    redis_client = request.app.state.redis_cache
    deleted_redis = _clear_tenant_redis(redis_client, tenant, other_slugs)

    # Milvus — this licitación's collection only
    store = _tenant_vector_store(request, tenant.collection)
    deleted_vectors = store.count_entities()
    store.drop_collection_if_exists()
    store.ensure_collection()

    # MinIO — only this licitación's <slug>/ objects (excluding other tenants for public)
    storage = MinIOStorage(settings)
    raw_cleared = storage.remove_objects(settings.minio_bucket_raw, prefix=tenant.key_prefix, exclude_prefixes=exclude)
    text_cleared = storage.remove_objects(settings.minio_bucket_text, prefix=tenant.key_prefix, exclude_prefixes=exclude)

    # Postgres — delete this licitación's rows inside its own schema (extracted_documents cascades)
    deleted_rows = 0

    async def _erase_pg(session: AsyncSession) -> None:
        nonlocal deleted_rows
        await session.execute(text("DELETE FROM extracted_documents"))
        result = await session.execute(text("DELETE FROM file_records"))
        deleted_rows = result.rowcount
        await session.execute(text("DELETE FROM sync_state"))
        await session.commit()

    await _reset_in_tenant(request, tenant.schema_name, _erase_pg)

    logger.info(
        "dashboard.erase_all",
        slug=tenant.slug or "public",
        deleted_redis=deleted_redis,
        deleted_vectors=deleted_vectors,
        raw_cleared=raw_cleared,
        text_cleared=text_cleared,
        deleted_rows=deleted_rows,
    )
    return DashboardActionResult(
        status="ok",
        detail=(
            f"Erased '{tenant.slug or 'public'}': {deleted_rows} Postgres rows, {raw_cleared} RAW + "
            f"{text_cleared} TEXT MinIO objects, {deleted_vectors} Milvus vectors, {deleted_redis} Redis keys."
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
