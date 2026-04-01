from __future__ import annotations

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build


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
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]

    # google-auth raises FileNotFoundError if file is missing
    # and ValueError if JSON is malformed.
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return build("drive", "v3", credentials=creds)
