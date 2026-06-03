"""Slug derivation and identifier-safety helpers for licitaciones.

A licitación slug is the single stable identifier reused across every isolation
boundary: the PostgreSQL schema (`lic_<slug>`), the Milvus collection
(`rag_<slug>`), the MinIO key prefix (`<slug>/`), the Redis key namespace, and
the chat URL hash. It is derived once from the display name at creation time and
then frozen — renaming a licitación never changes its slug.
"""

from __future__ import annotations

import re
import unicodedata

LICITACION_SCHEMA_PREFIX = "lic_"
LICITACION_COLLECTION_PREFIX = "rag_"

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
# search_path identifiers cannot be bound as query parameters, so any schema name
# interpolated into SQL must match this strict allowlist: 'public' or 'lic_<slug>'.
_SCHEMA_RE = re.compile(r"^(public|lic_[a-z0-9_]+)$")


def slugify(name: str) -> str:
    """Derive a stable, identifier-safe slug from a licitación display name.

    Lowercases, strips accents, and collapses every run of non-alphanumeric
    characters into a single underscore. The result matches ``[a-z0-9_]+``.

    Raises:
        ValueError: if the name reduces to an empty slug.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_only.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        raise ValueError(f"name {name!r} produces an empty slug")
    return slug


def validate_slug(slug: str) -> str:
    """Return the slug unchanged if it is identifier-safe, else raise ValueError."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}: must match [a-z0-9_]+")
    return slug


def schema_name_for_slug(slug: str) -> str:
    """Return the PostgreSQL schema name for a licitación slug (``lic_<slug>``)."""
    return f"{LICITACION_SCHEMA_PREFIX}{validate_slug(slug)}"


def collection_name_for_slug(slug: str) -> str:
    """Return the Milvus collection name for a licitación slug (``rag_<slug>``)."""
    return f"{LICITACION_COLLECTION_PREFIX}{validate_slug(slug)}"


def validate_schema_name(schema_name: str) -> str:
    """Guard a PostgreSQL schema name before interpolating it into ``SET search_path``.

    Identifiers cannot be parameterized, so this enforces a strict allowlist
    (``public`` or ``lic_<slug>``) as the injection guard.

    Raises:
        ValueError: if the schema name is not on the allowlist.
    """
    if not _SCHEMA_RE.match(schema_name):
        raise ValueError(f"invalid schema name {schema_name!r}")
    return schema_name


def pause_key(stage: str, slug: str) -> str:
    """Redis pause-flag key for a (stage, licitación) pair: ``rag:pause:<stage>:<slug>``.

    ``stage`` is one of ``ingest`` / ``transform`` / ``vectorize``. The slug-less
    ``rag:pause:<stage>`` key (without trailing slug) remains a global kill switch
    honored across every licitación.
    """
    return f"rag:pause:{stage}:{slug}"


def tenant_key(slug: str | None, key: str) -> str:
    """Prefix a MinIO object key with the licitación slug folder.

    ``slug`` of ``None`` or empty returns the key unchanged — preserving the flat,
    un-prefixed key space used by the pre-multitenancy 'Laboratorios Calidad' data.
    """
    if not slug:
        return key
    return f"{validate_slug(slug)}/{key}"
