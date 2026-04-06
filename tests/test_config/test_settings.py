"""Tests for config/settings.py — turns GREEN in Phase 1."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from config.settings import Settings


class TestSettings:
    def test_settings_loads_defaults(self):
        s = Settings()
        assert s.milvus_port == 19530
        assert s.embed_model == "nomic-embed-text"
        assert s.embed_dim == 768
        assert s.api_ssl_certfile == ""
        assert s.api_ssl_keyfile == ""

    def test_settings_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("MILVUS_PORT", "29530")
        monkeypatch.setenv("EMBED_MODEL", "custom-model")
        s = Settings()
        assert s.milvus_port == 29530
        assert s.embed_model == "custom-model"

    def test_secret_str_fields_are_protected(self):
        s = Settings(database_url=SecretStr("postgresql+asyncpg://secret@host/db"))
        text = repr(s)
        assert "secret@host" not in text

    def test_settings_validates_port_type(self):
        with pytest.raises(ValidationError):
            Settings(milvus_port="not-a-number")  # type: ignore[arg-type]
