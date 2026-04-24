"""Tests for OAuth refresh token encryption helpers."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from config.settings import Settings
from src.drive.token_crypto import decrypt_refresh_token, encrypt_refresh_token


def test_plaintext_when_no_encryption_key() -> None:
    s = Settings(token_encryption_key=SecretStr(""))
    raw = "my-refresh-token"
    enc = encrypt_refresh_token(s, raw)
    assert enc == raw
    assert decrypt_refresh_token(s, enc) == raw


def test_roundtrip_with_fernet_key() -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("utf-8")
    s = Settings(token_encryption_key=SecretStr(key))
    raw = "secret-refresh-value"
    enc = encrypt_refresh_token(s, raw)
    assert enc != raw
    assert decrypt_refresh_token(s, enc) == raw


def test_invalid_encryption_key_raises_clear_error() -> None:
    s = Settings(token_encryption_key=SecretStr("not-a-valid-fernet-key"))
    with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY is set but invalid"):
        encrypt_refresh_token(s, "token")
