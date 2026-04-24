"""Tests for Drive credential resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from config.settings import Settings
from src.drive.drive_credentials import build_drive_service_for_sync_repo, effective_drive_folder_id


def test_effective_folder_prefers_db_over_env() -> None:
    s = Settings(drive_folder_id="env-folder")
    repo = MagicMock()
    repo.get_drive_connection_sync.return_value = MagicMock(selected_folder_id="db-folder", refresh_token_enc="x")
    assert effective_drive_folder_id(s, repo) == "db-folder"


def test_effective_folder_falls_back_to_env() -> None:
    s = Settings(drive_folder_id="env-folder")
    repo = MagicMock()
    repo.get_drive_connection_sync.return_value = None
    assert effective_drive_folder_id(s, repo) == "env-folder"


def test_build_drive_uses_oauth_when_token_present() -> None:
    s = Settings(
        google_oauth_client_id="cid",
        google_oauth_client_secret=SecretStr("sec"),
        google_application_credentials="/nonexistent/sa.json",
    )
    repo = MagicMock()
    repo.get_drive_connection_sync.return_value = MagicMock(refresh_token_enc="enc", selected_folder_id="f1")
    with patch("src.drive.drive_credentials.decrypt_refresh_token", return_value="rt"):
        with patch("src.drive.drive_credentials.build_drive_service_from_refresh_token") as mock_oauth:
            mock_oauth.return_value = MagicMock()
            svc = build_drive_service_for_sync_repo(s, repo)
            assert svc is not None
            mock_oauth.assert_called_once_with("rt", s)


def test_build_drive_raises_when_no_credentials() -> None:
    s = Settings(google_application_credentials="/nonexistent/sa.json")
    repo = MagicMock()
    repo.get_drive_connection_sync.return_value = None
    with pytest.raises(RuntimeError, match="No Google Drive credentials"):
        build_drive_service_for_sync_repo(s, repo)
