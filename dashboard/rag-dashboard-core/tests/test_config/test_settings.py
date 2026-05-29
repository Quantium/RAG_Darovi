"""Tests for config/settings.py — turns GREEN in Phase 1."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from config.settings import Settings


class TestSettings:
    def test_settings_loads_defaults(self):
        """Verify Settings loads correct default values for key fields."""
        s = Settings()
        assert s.milvus_port == 19530
        assert s.embed_model == "nomic-embed-text"
        assert s.embed_dim == 768
        assert isinstance(s.api_ssl_certfile, str)
        assert isinstance(s.api_ssl_keyfile, str)

    def test_settings_reads_env_vars(self, monkeypatch):
        """Verify Settings overrides defaults with values from environment variables."""
        monkeypatch.setenv("MILVUS_PORT", "29530")
        monkeypatch.setenv("EMBED_MODEL", "custom-model")
        s = Settings()
        assert s.milvus_port == 29530
        assert s.embed_model == "custom-model"

    def test_secret_str_fields_are_protected(self):
        """Verify SecretStr fields are masked in the Settings repr output."""
        s = Settings(database_url=SecretStr("postgresql+asyncpg://secret@host/db"))
        text = repr(s)
        assert "secret@host" not in text

    def test_settings_validates_port_type(self):
        """Verify Settings raises ValidationError when milvus_port is given a non-integer string."""
        with pytest.raises(ValidationError):
            Settings(milvus_port="not-a-number")  # type: ignore[arg-type]

    def test_settings_validates_ingest_source(self):
        """Verify Settings raises ValidationError for an unsupported ingest_source value."""
        with pytest.raises(ValidationError):
            Settings(ingest_source="invalid-source")
