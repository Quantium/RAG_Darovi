"""Public Drive OAuth routes and session-gated folder APIs."""

from __future__ import annotations

import asyncio
import secrets
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from src.api.schemas import DriveBootstrapResponse, DriveFolderItem, SelectFolderRequest
from src.drive.auth import build_drive_service_from_refresh_token, service_account_credentials_available
from src.drive.oauth_http import (
    GoogleOAuthTokenError,
    build_google_authorize_url,
    exchange_authorization_code,
)
from src.drive.onboarding_phase import compute_pipeline_phase
from src.drive.token_crypto import decrypt_refresh_token, encrypt_refresh_token
from src.metadata.repository import MetadataRepository
from src.vectorizer.milvus_store import MilvusStore
from src.worker.tasks import run_incremental_sync

logger = structlog.get_logger()

drive_router = APIRouter(tags=["drive"])


def _verify_drive_setup_access(request: Request) -> None:
    settings: Settings = request.app.state.settings
    configured = settings.api_key.get_secret_value()
    if configured and request.headers.get("X-API-Key") == configured:
        return
    if request.session.get("drive_oauth_ok"):
        return
    raise HTTPException(status_code=401, detail="Drive setup requires browser session or X-API-Key")


DriveSetupAccess = Annotated[None, Depends(_verify_drive_setup_access)]


def _status_counts(files: list) -> dict[str, int]:
    counts = {"pending": 0, "downloaded": 0, "converted": 0, "embedded": 0, "failed": 0, "skipped": 0}
    for f in files:
        if f.status in counts:
            counts[f.status] += 1
        else:
            counts["pending"] += 1
    return counts


@drive_router.get("/drive/bootstrap", response_model=DriveBootstrapResponse)
async def drive_bootstrap(request: Request) -> DriveBootstrapResponse:
    settings: Settings = request.app.state.settings
    ingest_source = settings.ingest_source
    oauth_configured = bool(settings.google_oauth_client_id)
    sa_ready = service_account_credentials_available(settings) and bool(settings.drive_folder_id)

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        conn = await repo.get_drive_connection()
        files = await repo.list_by_status(None)

    counts = _status_counts(list(files))
    total = len(files)
    skipped = counts["skipped"]
    pipeline_phase = compute_pipeline_phase(
        total_files=total,
        pending=counts["pending"],
        downloaded=counts["downloaded"],
        converted=counts["converted"],
        embedded=counts["embedded"],
        failed=counts["failed"],
        skipped=skipped,
    )

    has_token = bool(conn and conn.refresh_token_enc)
    folder_selected = bool(conn and conn.selected_folder_id)

    if ingest_source == "local":
        return DriveBootstrapResponse(
            ingest_source="local",
            oauth_configured=False,
            connected=True,
            folder_selected=True,
            service_account_ready=False,
            onboarding_phase="ready",
            chat_ready=True,
            total_files=total,
            pending=counts["pending"],
            downloaded=counts["downloaded"],
            converted=counts["converted"],
            embedded=counts["embedded"],
            failed=counts["failed"],
            skipped=skipped,
        )

    if not oauth_configured:
        onboarding_phase = "ready" if sa_ready else "disconnected"
        chat_ready = sa_ready
        return DriveBootstrapResponse(
            ingest_source="drive",
            oauth_configured=False,
            connected=sa_ready,
            folder_selected=bool(settings.drive_folder_id) if sa_ready else False,
            service_account_ready=sa_ready,
            onboarding_phase=onboarding_phase,
            chat_ready=chat_ready,
            total_files=total,
            pending=counts["pending"],
            downloaded=counts["downloaded"],
            converted=counts["converted"],
            embedded=counts["embedded"],
            failed=counts["failed"],
            skipped=skipped,
        )

    if not has_token:
        onboarding_phase = "disconnected"
        chat_ready = False
    elif not folder_selected:
        onboarding_phase = "awaiting_folder"
        chat_ready = False
    else:
        onboarding_phase = pipeline_phase
        chat_ready = onboarding_phase == "ready"

    if onboarding_phase == "error":
        chat_ready = False

    return DriveBootstrapResponse(
        ingest_source="drive",
        oauth_configured=True,
        connected=has_token,
        folder_selected=folder_selected,
        service_account_ready=False,
        onboarding_phase=onboarding_phase,
        chat_ready=chat_ready,
        total_files=total,
        pending=counts["pending"],
        downloaded=counts["downloaded"],
        converted=counts["converted"],
        embedded=counts["embedded"],
        failed=counts["failed"],
        skipped=skipped,
    )


@drive_router.get("/auth/google/start")
async def google_oauth_start(request: Request) -> RedirectResponse:
    settings: Settings = request.app.state.settings
    if not settings.google_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    url = build_google_authorize_url(settings, state)
    return RedirectResponse(url, status_code=302)


@drive_router.get("/auth/google/callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        logger.warning("drive.oauth.callback_error", error=error)
        raise HTTPException(status_code=400, detail=error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    expected = request.session.get("oauth_state")
    if not expected or state != expected:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    request.session.pop("oauth_state", None)

    settings: Settings = request.app.state.settings
    try:
        tokens = await exchange_authorization_code(settings, code)
    except GoogleOAuthTokenError as exc:
        logger.warning("drive.oauth.token_exchange_failed", error=exc.message)
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        logger.error("drive.oauth.token_exchange_config_error", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        logger.error("drive.oauth.token_exchange_http_error", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Could not reach Google token endpoint. Check network and try again.",
        ) from exc

    refresh = tokens.get("refresh_token")
    if not refresh:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned. Revoke app access in Google Account settings and try again.",
        )

    try:
        enc = encrypt_refresh_token(settings, refresh)
        async with AsyncSession(request.app.state.engine) as session:
            repo = MetadataRepository(session)
            await repo.save_drive_oauth_token(enc)
    except ValueError as exc:
        logger.error("drive.oauth.persist_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.exception("drive.oauth.database_error")
        raise HTTPException(
            status_code=503,
            detail="Database error while saving Google Drive credentials. Check DATABASE_URL and migrations.",
        ) from exc

    request.session["drive_oauth_ok"] = True
    return RedirectResponse("/", status_code=302)


@drive_router.get("/drive/folders", response_model=list[DriveFolderItem])
async def list_drive_folders(
    request: Request,
    _access: DriveSetupAccess,
    parent_id: str = "root",
) -> list[DriveFolderItem]:
    settings: Settings = request.app.state.settings
    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        row = await repo.get_drive_connection()
        if not row or not row.refresh_token_enc:
            raise HTTPException(status_code=400, detail="Google Drive is not connected")
        enc_token = row.refresh_token_enc

    try:
        refresh = decrypt_refresh_token(settings, enc_token)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    svc = build_drive_service_from_refresh_token(refresh, settings)

    def _list() -> list[dict]:
        q_parts = ["mimeType='application/vnd.google-apps.folder'", "trashed=false"]
        if parent_id == "root":
            q_parts.append("'root' in parents")
        else:
            q_parts.append(f"'{parent_id}' in parents")
        q = " and ".join(q_parts)
        resp = svc.files().list(q=q, spaces="drive", fields="nextPageToken, files(id, name)", pageSize=100).execute()
        return resp.get("files", [])

    raw = await asyncio.to_thread(_list)
    return [DriveFolderItem(id=f["id"], name=f.get("name", "")) for f in raw]


@drive_router.post("/drive/select-folder")
async def select_drive_folder(request: Request, body: SelectFolderRequest, _access: DriveSetupAccess) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    store = MilvusStore(settings)

    async with AsyncSession(request.app.state.engine) as session:
        repo = MetadataRepository(session)
        await repo.delete_all_file_records()
        await repo.update_page_token("")
        await repo.set_drive_selected_folder(body.folder_id)

    try:
        store.drop_collection_if_exists()
        store.ensure_collection()
    except Exception as exc:
        logger.error("drive.select_folder.milvus_reset_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Could not reset vector index") from exc

    run_incremental_sync.delay()
    return {"status": "ok"}


__all__ = ["drive_router"]
