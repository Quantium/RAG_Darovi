"""Infrastructure provisioning for a licitación tenant: its PostgreSQL schema +
per-tenant tables, and its Milvus collection. All operations are idempotent so a
failed provisioning attempt can be safely retried (resumed).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from config.settings import Settings
from src.tenant.slug import validate_schema_name
from src.vectorizer.milvus_store import MilvusStore

# Tables replicated into each licitación schema. Global tables (licitaciones, chat_users)
# stay in public and are intentionally excluded.
TENANT_TABLES = ("file_records", "extracted_documents", "sync_state", "chat_interactions")


async def provision_tenant_schema(conn: AsyncConnection, schema_name: str) -> None:
    """Create the licitación PostgreSQL schema and its per-tenant tables (idempotent).

    Each table is cloned from the canonical public table with
    ``CREATE TABLE ... (LIKE public.<t> INCLUDING ALL)``, guaranteeing structural parity
    (columns, defaults, indexes, primary key) without duplicating DDL. No-op on
    non-PostgreSQL backends — the aiosqlite unit-test database has a single schema.

    Raises:
        ValueError: if the schema name is not a valid ``lic_<slug>`` tenant schema
            (refuses to ever target ``public``).
    """
    validate_schema_name(schema_name)
    if schema_name == "public" or not schema_name.startswith("lic_"):
        raise ValueError(f"refusing to provision non-tenant schema {schema_name!r}")
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
    for table in TENANT_TABLES:
        await conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL)'
            )
        )


def create_tenant_collection(settings: Settings, collection_name: str) -> None:
    """Create the licitación's Milvus collection if it does not already exist (idempotent)."""
    MilvusStore(settings, collection_name=collection_name).ensure_collection()
