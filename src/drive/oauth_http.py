"""Google OAuth2 authorization URL and token exchange (no extra deps)."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlencode

import httpx
import structlog

from config.settings import Settings

logger = structlog.get_logger()

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleOAuthTokenError(Exception):
    """Google token endpoint returned an error (e.g. invalid_grant, redirect_uri_mismatch)."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def build_google_authorize_url(settings: Settings, state: str) -> str:
    if not settings.google_oauth_client_id:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID is not configured")
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": DRIVE_READONLY_SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_authorization_code(settings: Settings, code: str) -> dict[str, Any]:
    """Exchange auth code for tokens; returns JSON body from Google."""
    secret = settings.google_oauth_client_secret.get_secret_value()
    if not secret:
        raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET is not configured")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if resp.is_error:
            detail = "Token exchange failed"
            try:
                body = resp.json()
                if isinstance(body, dict):
                    err = body.get("error")
                    desc = body.get("error_description")
                    if desc:
                        detail = str(desc)
                    elif err:
                        detail = str(err)
            except Exception:
                detail = (resp.text or detail)[:300]
            logger.error(
                "drive.oauth.google_token_error",
                status_code=resp.status_code,
                detail=detail,
            )
            raise GoogleOAuthTokenError(detail)
        return cast(dict[str, Any], resp.json())
