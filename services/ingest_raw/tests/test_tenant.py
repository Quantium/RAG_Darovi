"""Tests for ingest_raw multi-tenancy: helpers, scoped source adapter, orchestration."""

from __future__ import annotations

import pytest

import app.tenant_service as tenant_service
from app.settings import Settings
from app.sources import LocalSourceAdapter
from app.tenant import (
    LEGACY_LICITACION,
    Licitacion,
    tenant_key,
    validate_schema_name,
    validate_slug,
)
from app.tenant_service import TenantIngestService


class TestHelpers:
    def test_tenant_key(self):
        assert tenant_key("", "f/x.pdf") == "f/x.pdf"
        assert tenant_key(None, "f/x.pdf") == "f/x.pdf"
        assert tenant_key("obra_norte", "f/x.pdf") == "obra_norte/f/x.pdf"

    @pytest.mark.parametrize("bad", ["Obra", "obra-norte", ""])
    def test_validate_slug_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_slug(bad)

    @pytest.mark.parametrize("ok", ["public", "lic_obra_norte"])
    def test_validate_schema_ok(self, ok):
        assert validate_schema_name(ok) == ok

    @pytest.mark.parametrize("bad", ["lic_Obra", "evil; DROP", "schema"])
    def test_validate_schema_rejects(self, bad):
        with pytest.raises(ValueError):
            validate_schema_name(bad)

    def test_key_prefix_property(self):
        assert Licitacion("laboratorios_calidad", "", "public", "active").key_prefix == ""
        assert Licitacion("obra_norte", "obra_norte", "lic_obra_norte", "active").key_prefix == "obra_norte/"


class TestScopedSourceAdapter:
    def _make_tree(self, tmp_path):
        (tmp_path / "root_file.txt").write_text("root")
        (tmp_path / "obra_norte").mkdir()
        (tmp_path / "obra_norte" / "sub.txt").write_text("sub")

    def test_root_tenant_excludes_other_subfolders(self, tmp_path):
        self._make_tree(tmp_path)
        settings = Settings(local_source_folder=str(tmp_path))
        adapter = LocalSourceAdapter(settings, sub_path="", exclude_prefixes={"obra_norte"})
        names = {f.name for page in adapter.iter_pages(100) for f in page}
        assert names == {"root_file.txt"}

    def test_subfolder_tenant_scopes_to_subpath(self, tmp_path):
        self._make_tree(tmp_path)
        settings = Settings(local_source_folder=str(tmp_path))
        adapter = LocalSourceAdapter(settings, sub_path="obra_norte")
        files = [f for page in adapter.iter_pages(100) for f in page]
        assert {f.name for f in files} == {"sub.txt"}
        assert files[0].path_hint == "sub.txt"  # relative to the scoped root


class TestTenantOrchestration:
    def test_run_once_aggregates_and_isolates_failures(self, monkeypatch):
        settings = Settings(local_source_folder="/tmp")
        svc = TenantIngestService(settings)
        licitaciones = [
            Licitacion("a", "a", "lic_a", "active"),
            Licitacion("b", "b", "lic_b", "active"),
        ]
        monkeypatch.setattr(tenant_service, "read_active_licitaciones", lambda engine: licitaciones)

        calls: list[tuple[str, set[str]]] = []

        def fake_run_one(lic, exclude_prefixes):
            calls.append((lic.slug, set(exclude_prefixes)))
            if lic.slug == "b":
                raise RuntimeError("boom")
            return {"scanned": 2, "updated": 1, "skipped": 0}

        monkeypatch.setattr(svc, "_run_one", fake_run_one)
        totals = svc.run_once()

        assert totals["licitaciones"] == 1
        assert totals["errors"] == 1
        assert totals["scanned"] == 2 and totals["updated"] == 1
        assert ("a", {"b"}) in calls and ("b", {"a"}) in calls

    def test_run_once_legacy_fallback_when_registry_empty(self, monkeypatch):
        settings = Settings(local_source_folder="/tmp")
        svc = TenantIngestService(settings)
        monkeypatch.setattr(tenant_service, "read_active_licitaciones", lambda engine: [])
        seen: list[str] = []
        monkeypatch.setattr(svc, "_run_one", lambda lic, exclude_prefixes: seen.append(lic.schema_name) or {"scanned": 0, "updated": 0, "skipped": 0})
        svc.run_once()
        assert seen == [LEGACY_LICITACION.schema_name] == ["public"]
