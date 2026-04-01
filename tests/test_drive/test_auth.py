"""Tests for src/drive/auth.py — turns GREEN in Phase 3."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.drive.auth import build_drive_service


class TestDriveAuth:
    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    @patch("src.drive.auth.build")
    def test_build_service_from_json(self, mock_build, mock_creds):
        mock_creds.return_value = MagicMock()
        service = build_drive_service("credentials/valid.json")
        assert service is not None
        mock_build.assert_called_once()

    def test_build_service_missing_file(self):
        with pytest.raises(FileNotFoundError):
            build_drive_service("/nonexistent/path.json")

    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    def test_build_service_invalid_json(self, mock_creds):
        mock_creds.side_effect = ValueError("Invalid JSON")
        with pytest.raises(ValueError):
            build_drive_service("credentials/bad.json")

    @patch("src.drive.auth.service_account.Credentials.from_service_account_file")
    @patch("src.drive.auth.build")
    def test_scopes_include_readonly(self, mock_build, mock_creds):
        mock_creds.return_value = MagicMock()
        build_drive_service("credentials/valid.json")
        call_args = mock_creds.call_args
        scopes = call_args[1].get("scopes") or call_args[0][1] if len(call_args[0]) > 1 else None
        assert any("drive.readonly" in s for s in (scopes or []))
