"""Tests for extract_text multi-tenancy: helpers and the lock-managing orchestrator."""

from __future__ import annotations

import pytest

import app.tenant_service as tenant_service
from app.settings import Settings
from app.tenant import Licitacion, tenant_key, validate_schema_name, validate_slug
from app.tenant_service import TenantExtractService


class TestHelpers:
    def test_tenant_key(self):
        assert tenant_key("", "f1.md") == "f1.md"
        assert tenant_key("obra_norte", "f1.md") == "obra_norte/f1.md"

    @pytest.mark.parametrize("bad", ["Obra", "obra-norte", ""])
    def test_validate_slug_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_slug(bad)

    @pytest.mark.parametrize("bad", ["lic_Obra", "evil; DROP", "schema"])
    def test_validate_schema_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_schema_name(bad)

    def test_key_prefix_property(self):
        assert Licitacion("laboratorios_calidad", "", "public", "active").key_prefix == ""
        assert Licitacion("obra_norte", "", "lic_obra_norte", "active").key_prefix == "obra_norte/"


def _patch_lock(monkeypatch, acquired: bool):
    state = {"acquired": False, "released": False}

    def fake_acquire(self, lock_id):
        state["acquired"] = True
        return acquired

    def fake_release(self, lock_id):
        state["released"] = True

    monkeypatch.setattr(tenant_service.MetadataRepository, "try_acquire_lock", fake_acquire)
    monkeypatch.setattr(tenant_service.MetadataRepository, "release_lock", fake_release)
    return state


class TestTenantOrchestration:
    def test_holds_lock_once_and_isolates_failures(self, monkeypatch):
        svc = TenantExtractService(Settings())
        lock = _patch_lock(monkeypatch, acquired=True)
        monkeypatch.setattr(
            tenant_service,
            "read_active_licitaciones",
            lambda engine: [Licitacion("a", "", "lic_a", "active"), Licitacion("b", "", "lic_b", "active")],
        )

        def fake_run_one(lic, storage):
            if lic.slug == "b":
                raise RuntimeError("boom")
            return {"scanned": 1, "updated": 1, "failed": 0}

        monkeypatch.setattr(svc, "_run_one", fake_run_one)
        totals = svc.run_once()

        assert lock["acquired"] and lock["released"]
        assert totals["licitaciones"] == 1
        assert totals["errors"] == 1
        assert totals["scanned"] == 1 and totals["updated"] == 1

    def test_skips_when_lock_unavailable(self, monkeypatch):
        svc = TenantExtractService(Settings())
        _patch_lock(monkeypatch, acquired=False)

        def fail(engine):
            raise AssertionError("must not read registry when lock is unavailable")

        monkeypatch.setattr(tenant_service, "read_active_licitaciones", fail)
        totals = svc.run_once()
        assert totals == {"scanned": 0, "updated": 0, "failed": 0, "licitaciones": 0, "errors": 0}

    def test_legacy_fallback_when_registry_empty(self, monkeypatch):
        svc = TenantExtractService(Settings())
        _patch_lock(monkeypatch, acquired=True)
        monkeypatch.setattr(tenant_service, "read_active_licitaciones", lambda engine: [])
        seen: list[str] = []
        monkeypatch.setattr(
            svc,
            "_run_one",
            lambda lic, storage: (seen.append(lic.schema_name) or {"scanned": 0, "updated": 0, "failed": 0}),
        )
        svc.run_once()
        assert seen == ["public"]
