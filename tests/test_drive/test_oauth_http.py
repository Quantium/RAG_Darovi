"""Tests for Google OAuth HTTP helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from config.settings import Settings
from src.drive.oauth_http import GoogleOAuthTokenError, exchange_authorization_code


@pytest.mark.asyncio
async def test_exchange_maps_google_error_json_to_google_oauth_token_error() -> None:
    settings = Settings(
        google_oauth_client_id="id",
        google_oauth_client_secret=SecretStr("secret"),
    )
    mock_resp = MagicMock()
    mock_resp.is_error = True
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "redirect_uri_mismatch",
    }
    mock_resp.text = ""

    with patch("src.drive.oauth_http.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(GoogleOAuthTokenError) as excinfo:
            await exchange_authorization_code(settings, "auth-code")
    assert excinfo.value.message == "redirect_uri_mismatch"
