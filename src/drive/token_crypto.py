"""Encrypt/decrypt Google OAuth refresh tokens at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

import structlog

from config.settings import Settings

logger = structlog.get_logger()


def encrypt_refresh_token(settings: Settings, plaintext: str) -> str:
    key = settings.token_encryption_key.get_secret_value().strip()
    if not key:
        logger.warning("drive.oauth.token_stored_plaintext", reason="TOKEN_ENCRYPTION_KEY not set")
        return plaintext
    try:
        f = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        logger.error("drive.oauth.invalid_encryption_key", error=str(exc))
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY is set but invalid: it must be a Fernet key "
            "(32 url-safe base64 bytes). Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(settings: Settings, ciphertext: str) -> str:
    key = settings.token_encryption_key.get_secret_value().strip()
    if not key:
        return ciphertext
    try:
        f = Fernet(key.encode("utf-8"))
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("drive.oauth.decrypt_failed", reason="invalid token or wrong key")
        raise ValueError("Could not decrypt stored refresh token") from None
