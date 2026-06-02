"""Tests for src/tenant/slug.py."""

from __future__ import annotations

import pytest

from src.tenant.slug import (
    collection_name_for_slug,
    schema_name_for_slug,
    slugify,
    tenant_key,
    validate_schema_name,
    validate_slug,
)


class TestSlugify:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Obra Norte 2026", "obra_norte_2026"),
            ("Licitación Áéíóú", "licitacion_aeiou"),
            ("  Multiple   spaces  ", "multiple_spaces"),
            ("Guíon-medio/barra", "guion_medio_barra"),
            ("UPPER_case", "upper_case"),
            ("a..b--c", "a_b_c"),
        ],
    )
    def test_slugify(self, name: str, expected: str) -> None:
        assert slugify(name) == expected

    @pytest.mark.parametrize("name", ["   ", "!!!", "—"])
    def test_slugify_empty_raises(self, name: str) -> None:
        with pytest.raises(ValueError):
            slugify(name)


class TestValidateSlug:
    def test_valid(self) -> None:
        assert validate_slug("obra_norte_2026") == "obra_norte_2026"

    @pytest.mark.parametrize("bad", ["Obra Norte", "obra-norte", "lic;drop", "", "UPPER"])
    def test_invalid(self, bad: str) -> None:
        with pytest.raises(ValueError):
            validate_slug(bad)


class TestNameBuilders:
    def test_schema_name(self) -> None:
        assert schema_name_for_slug("obra_norte") == "lic_obra_norte"

    def test_collection_name(self) -> None:
        assert collection_name_for_slug("obra_norte") == "rag_obra_norte"

    def test_builders_reject_bad_slug(self) -> None:
        with pytest.raises(ValueError):
            schema_name_for_slug("bad-slug")
        with pytest.raises(ValueError):
            collection_name_for_slug("bad slug")


class TestValidateSchemaName:
    @pytest.mark.parametrize("ok", ["public", "lic_obra_norte", "lic_x1"])
    def test_valid(self, ok: str) -> None:
        assert validate_schema_name(ok) == ok

    @pytest.mark.parametrize(
        "bad",
        ["lic_Obra", "public; DROP SCHEMA x", "lic_obra-norte", "random", "lic_", "LIC_x"],
    )
    def test_invalid(self, bad: str) -> None:
        with pytest.raises(ValueError):
            validate_schema_name(bad)


class TestTenantKey:
    def test_no_slug_unchanged(self) -> None:
        assert tenant_key(None, "abc/file.pdf") == "abc/file.pdf"
        assert tenant_key("", "abc/file.pdf") == "abc/file.pdf"

    def test_with_slug_prefixed(self) -> None:
        assert tenant_key("obra_norte", "abc/file.pdf") == "obra_norte/abc/file.pdf"

    def test_bad_slug_raises(self) -> None:
        with pytest.raises(ValueError):
            tenant_key("bad-slug", "x")
