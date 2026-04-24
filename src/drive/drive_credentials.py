"""Resolve Google Drive API client and folder id for workers and API routes."""

from __future__ import annotations

from googleapiclient.discovery import Resource

from config.settings import Settings
from src.drive.auth import (
    build_drive_service,
    build_drive_service_from_refresh_token,
    service_account_credentials_available,
)
from src.drive.token_crypto import decrypt_refresh_token
from src.metadata.repository import SyncMetadataRepository


def build_drive_service_for_sync_repo(settings: Settings, repo: SyncMetadataRepository) -> Resource:
    """Prefer OAuth refresh token from DB; fall back to service account JSON file."""
    row = repo.get_drive_connection_sync()
    if row and row.refresh_token_enc:
        refresh = decrypt_refresh_token(settings, row.refresh_token_enc)
        return build_drive_service_from_refresh_token(refresh, settings)
    if service_account_credentials_available(settings):
        return build_drive_service(settings.google_application_credentials)
    raise RuntimeError(
        "No Google Drive credentials: complete OAuth in the UI or configure "
        "GOOGLE_APPLICATION_CREDENTIALS and DRIVE_FOLDER_ID."
    )


def effective_drive_folder_id(settings: Settings, repo: SyncMetadataRepository) -> str:
    """Prefer folder chosen in UI (OAuth); otherwise env DRIVE_FOLDER_ID."""
    row = repo.get_drive_connection_sync()
    if row and row.selected_folder_id.strip():
        return row.selected_folder_id.strip()
    return settings.drive_folder_id
