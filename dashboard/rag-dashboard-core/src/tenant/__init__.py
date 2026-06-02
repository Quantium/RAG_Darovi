"""Multi-tenancy primitives: slug derivation, schema/collection naming, and
tenant-scoped database sessions. Pure helpers live in `slug`; session context
managers live in `session`. The Licitacion ORM model and its repository live in
`src.metadata.repository` alongside the other models.
"""

from __future__ import annotations

from src.tenant.slug import (
    LICITACION_COLLECTION_PREFIX,
    LICITACION_SCHEMA_PREFIX,
    collection_name_for_slug,
    schema_name_for_slug,
    slugify,
    tenant_key,
    validate_schema_name,
    validate_slug,
)
from src.tenant.session import tenant_session, tenant_session_sync

__all__ = [
    "LICITACION_COLLECTION_PREFIX",
    "LICITACION_SCHEMA_PREFIX",
    "collection_name_for_slug",
    "schema_name_for_slug",
    "slugify",
    "tenant_key",
    "tenant_session",
    "tenant_session_sync",
    "validate_schema_name",
    "validate_slug",
]
