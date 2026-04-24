from __future__ import annotations

import os

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from config.settings import Settings

DRIVE_READONLY_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)


def build_drive_service(credentials_path: str) -> Resource:
    """Build a Google Drive service using a service account JSON file.

    Args:
        credentials_path: Path to the service account JSON file.

    Returns:
        A Google Drive API resource.

    Raises:
        FileNotFoundError: If the credentials file does not exist.
        ValueError: If the credentials file is malformed.
    """
    scopes = list(DRIVE_READONLY_SCOPES)

    # google-auth raises FileNotFoundError if file is missing
    # and ValueError if JSON is malformed.
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return build("drive", "v3", credentials=creds)


def build_drive_service_from_refresh_token(refresh_token: str, settings: Settings) -> Resource:
    """Build Drive API client using a user OAuth refresh token."""
    if not settings.google_oauth_client_id:
        raise ValueError("google_oauth_client_id is not configured")
    client_secret = settings.google_oauth_client_secret.get_secret_value()
    if not client_secret:
        raise ValueError("google_oauth_client_secret is not configured")
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=client_secret,
        scopes=list(DRIVE_READONLY_SCOPES),
    )
    return build("drive", "v3", credentials=creds, static_discovery=False)


def service_account_credentials_available(settings: Settings) -> bool:
    path = settings.google_application_credentials
    return bool(path) and os.path.isfile(path)
