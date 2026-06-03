"""Licitación lifecycle service: create / edit / pause / resume / archive.

Provisioning is transactional and idempotent. The registry row is reserved first
(status='provisioning'), then the PostgreSQL schema + Milvus collection are created;
on success the row flips to 'active', on failure to 'failed' (which a later create()
with the same name resumes). Archiving never drops the schema or collection — it only
sets status='archived' and purges the licitación's ephemeral Redis keys; permanent
deletion is a manual human operation against the databases.

Schema and collection provisioners are injectable so the orchestration can be unit
tested on sqlite without a live PostgreSQL/Milvus.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from config.settings import Settings
from src.metadata.repository import (
    LICITACION_STATUS_ACTIVE,
    LICITACION_STATUS_ARCHIVED,
    LICITACION_STATUS_FAILED,
    LICITACION_STATUS_PAUSED,
    LICITACION_STATUS_PROVISIONING,
    Licitacion,
    LicitacionRepository,
)
from src.tenant.provisioning import create_tenant_collection, provision_tenant_schema
from src.tenant.slug import (
    collection_name_for_slug,
    pause_key,
    schema_name_for_slug,
    slugify,
    validate_slug,
)

PAUSE_STAGES = ("ingest", "transform", "vectorize")

SchemaProvisioner = Callable[[AsyncConnection, str], Awaitable[None]]
CollectionProvisioner = Callable[[Settings, str], None]


class LicitacionError(Exception):
    """Base class for licitación service errors."""


class LicitacionValidationError(LicitacionError):
    """Invalid input (e.g. empty name, or a name that yields an empty slug). -> HTTP 400."""


class LicitacionConflict(LicitacionError):
    """Name/slug already in use by a non-failed licitación. -> HTTP 409."""


class LicitacionNotFound(LicitacionError):
    """No licitación with the given id. -> HTTP 404."""


class LicitacionService:
    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        redis_client,
        *,
        schema_provisioner: SchemaProvisioner | None = None,
        collection_provisioner: CollectionProvisioner | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._redis = redis_client
        self._provision_schema = schema_provisioner or provision_tenant_schema
        self._provision_collection = collection_provisioner or create_tenant_collection

    def _session(self) -> AsyncSession:
        # expire_on_commit=False keeps column values readable after the session closes,
        # so returned rows can be serialized by the route without a detached re-load.
        return AsyncSession(self._engine, expire_on_commit=False)

    async def list(self, include_archived: bool = False) -> Sequence[Licitacion]:
        """Return licitaciones ordered by name (archived excluded unless requested)."""
        async with self._session() as session:
            return await LicitacionRepository(session).list_all(include_archived=include_archived)

    async def get(self, licitacion_id: str) -> Licitacion:
        """Return a licitación by id, raising LicitacionNotFound if absent."""
        async with self._session() as session:
            row = await LicitacionRepository(session).get_by_id(licitacion_id)
        if row is None:
            raise LicitacionNotFound(licitacion_id)
        return row

    async def create(self, name: str, source_path: str = "") -> Licitacion:
        """Create (or resume a previously failed) licitación and provision its infrastructure."""
        name = (name or "").strip()
        if not name:
            raise LicitacionValidationError("name is required")
        try:
            slug = validate_slug(slugify(name))
        except ValueError as exc:
            raise LicitacionValidationError(str(exc)) from exc
        schema_name = schema_name_for_slug(slug)
        collection = collection_name_for_slug(slug)

        # Reserve the registry row (status=provisioning) or resume a prior failed attempt.
        async with self._session() as session:
            repo = LicitacionRepository(session)
            by_slug = await repo.get_by_slug(slug)
            by_name = await self._get_by_name(session, name)
            if by_slug is not None and by_slug.status != LICITACION_STATUS_FAILED:
                raise LicitacionConflict(f"licitación '{name}' (slug '{slug}') already exists")
            if by_name is not None and (by_slug is None or by_name.id != by_slug.id):
                raise LicitacionConflict(f"name '{name}' already in use")
            if by_slug is None:
                row = Licitacion(
                    id=str(uuid.uuid4()),
                    name=name,
                    slug=slug,
                    source_path=source_path or "",
                    schema_name=schema_name,
                    milvus_collection=collection,
                    status=LICITACION_STATUS_PROVISIONING,
                )
                session.add(row)
            else:  # resume a failed attempt — identifiers are unchanged
                row = by_slug
                row.name = name
                row.source_path = source_path or ""
                row.status = LICITACION_STATUS_PROVISIONING
                row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            licitacion_id = row.id

        # Provision infrastructure (idempotent). On any failure mark 'failed' and re-raise.
        try:
            async with self._engine.begin() as conn:
                await self._provision_schema(conn, schema_name)
            await self._run_collection_provisioner(collection)
        except Exception:
            await self._set_status(licitacion_id, LICITACION_STATUS_FAILED)
            raise

        return await self._set_status(licitacion_id, LICITACION_STATUS_ACTIVE)

    async def edit(
        self, licitacion_id: str, name: str | None = None, source_path: str | None = None
    ) -> Licitacion:
        """Update display fields only. slug / schema_name / milvus_collection are immutable."""
        async with self._session() as session:
            repo = LicitacionRepository(session)
            row = await repo.get_by_id(licitacion_id)
            if row is None:
                raise LicitacionNotFound(licitacion_id)
            if name is not None:
                name = name.strip()
                if not name:
                    raise LicitacionValidationError("name cannot be empty")
                other = await self._get_by_name(session, name)
                if other is not None and other.id != row.id:
                    raise LicitacionConflict(f"name '{name}' already in use")
                row.name = name  # display label only; slug stays frozen
            if source_path is not None:
                row.source_path = source_path
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return row

    async def pause(self, licitacion_id: str) -> Licitacion:
        """Pause ingest/transform/vectorize for the licitación (status + Redis pause flags)."""
        row = await self._set_status(licitacion_id, LICITACION_STATUS_PAUSED)
        for stage in PAUSE_STAGES:
            self._redis.set(pause_key(stage, row.slug), "1")
        return row

    async def resume(self, licitacion_id: str) -> Licitacion:
        """Resume a paused licitación (status active + clear Redis pause flags)."""
        row = await self._set_status(licitacion_id, LICITACION_STATUS_ACTIVE)
        for stage in PAUSE_STAGES:
            self._redis.delete(pause_key(stage, row.slug))
        return row

    async def archive(self, licitacion_id: str) -> Licitacion:
        """Soft-delete: status='archived', purge ephemeral Redis keys. Data is NOT dropped."""
        row = await self._set_status(licitacion_id, LICITACION_STATUS_ARCHIVED)
        self._purge_redis(row.slug)
        return row

    async def _set_status(self, licitacion_id: str, status: str) -> Licitacion:
        async with self._session() as session:
            repo = LicitacionRepository(session)
            row = await repo.get_by_id(licitacion_id)
            if row is None:
                raise LicitacionNotFound(licitacion_id)
            row.status = status
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return row

    async def _get_by_name(self, session: AsyncSession, name: str) -> Licitacion | None:
        result = await session.execute(select(Licitacion).where(Licitacion.name == name))
        return result.scalar_one_or_none()

    async def _run_collection_provisioner(self, collection: str) -> None:
        # pymilvus is sync; run it off the event loop so the admin call doesn't block it.
        from starlette.concurrency import run_in_threadpool

        await run_in_threadpool(self._provision_collection, self._settings, collection)

    def _purge_redis(self, slug: str) -> None:
        """Delete the licitación's ephemeral Redis keys (pause flags + conversation history)."""
        for stage in PAUSE_STAGES:
            self._redis.delete(pause_key(stage, slug))
        try:
            for key in self._redis.scan_iter(match=f"chatbot:conv:{slug}:*"):
                self._redis.delete(key)
        except Exception:  # pragma: no cover - redis backend without scan_iter
            pass
