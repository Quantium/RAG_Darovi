"""Licitaciones CRUD API — create / list / edit / pause / resume / archive tenants."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.app import verify_api_key
from src.api.dashboard_routes import _require_dashboard_confirm
from src.tenant.service import (
    LicitacionConflict,
    LicitacionNotFound,
    LicitacionService,
    LicitacionValidationError,
)

logger = structlog.get_logger()

licitaciones_router = APIRouter(tags=["licitaciones"])


class LicitacionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_path: str = Field(default="", max_length=1024)


class LicitacionEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    source_path: Optional[str] = Field(default=None, max_length=1024)


class LicitacionOut(BaseModel):
    id: str
    name: str
    slug: str
    source_path: str
    schema_name: str
    milvus_collection: str
    status: str

    model_config = {"from_attributes": True}


def _service(request: Request) -> LicitacionService:
    """Build a LicitacionService from app state (engine, settings, redis cache)."""
    return LicitacionService(
        request.app.state.engine,
        request.app.state.settings,
        request.app.state.redis_cache,
    )


@licitaciones_router.get(
    "/licitaciones",
    response_model=list[LicitacionOut],
    dependencies=[Depends(verify_api_key)],
)
async def list_licitaciones(request: Request, include_archived: bool = False) -> list[LicitacionOut]:
    """List licitaciones ordered by name (archived excluded unless ?include_archived=true)."""
    rows = await _service(request).list(include_archived=include_archived)
    return [LicitacionOut.model_validate(row) for row in rows]


@licitaciones_router.post(
    "/licitaciones",
    response_model=LicitacionOut,
    status_code=201,
    dependencies=[Depends(verify_api_key)],
)
async def create_licitacion(request: Request, body: LicitacionCreate) -> LicitacionOut:
    """Create a licitación: reserve registry row, provision PG schema + Milvus collection."""
    try:
        row = await _service(request).create(name=body.name, source_path=body.source_path)
    except LicitacionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LicitacionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("licitacion.created", slug=row.slug, schema=row.schema_name, collection=row.milvus_collection)
    return LicitacionOut.model_validate(row)


@licitaciones_router.patch(
    "/licitaciones/{licitacion_id}",
    response_model=LicitacionOut,
    dependencies=[Depends(verify_api_key)],
)
async def edit_licitacion(request: Request, licitacion_id: str, body: LicitacionEdit) -> LicitacionOut:
    """Edit a licitación's display name and/or source_path. Identifiers are immutable."""
    try:
        row = await _service(request).edit(licitacion_id, name=body.name, source_path=body.source_path)
    except LicitacionNotFound as exc:
        raise HTTPException(status_code=404, detail="licitación not found") from exc
    except LicitacionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LicitacionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LicitacionOut.model_validate(row)


@licitaciones_router.post(
    "/licitaciones/{licitacion_id}/pause",
    response_model=LicitacionOut,
    dependencies=[Depends(verify_api_key)],
)
async def pause_licitacion(request: Request, licitacion_id: str) -> LicitacionOut:
    """Pause ingest/transform/vectorize for the licitación."""
    try:
        row = await _service(request).pause(licitacion_id)
    except LicitacionNotFound as exc:
        raise HTTPException(status_code=404, detail="licitación not found") from exc
    logger.info("licitacion.paused", licitacion_id=licitacion_id)
    return LicitacionOut.model_validate(row)


@licitaciones_router.post(
    "/licitaciones/{licitacion_id}/resume",
    response_model=LicitacionOut,
    dependencies=[Depends(verify_api_key)],
)
async def resume_licitacion(request: Request, licitacion_id: str) -> LicitacionOut:
    """Resume a paused licitación."""
    try:
        row = await _service(request).resume(licitacion_id)
    except LicitacionNotFound as exc:
        raise HTTPException(status_code=404, detail="licitación not found") from exc
    logger.info("licitacion.resumed", licitacion_id=licitacion_id)
    return LicitacionOut.model_validate(row)


@licitaciones_router.delete(
    "/licitaciones/{licitacion_id}",
    response_model=LicitacionOut,
    dependencies=[Depends(verify_api_key), Depends(_require_dashboard_confirm)],
)
async def archive_licitacion(request: Request, licitacion_id: str) -> LicitacionOut:
    """Archive a licitación (soft delete). Data is NOT dropped — manual human deletion only."""
    try:
        row = await _service(request).archive(licitacion_id)
    except LicitacionNotFound as exc:
        raise HTTPException(status_code=404, detail="licitación not found") from exc
    logger.info("licitacion.archived", slug=row.slug)
    return LicitacionOut.model_validate(row)
