"""add licitaciones registry

Revision ID: 20260602_0006
Revises: 20260531_0005
Create Date: 2026-06-02 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260602_0006"
down_revision = "20260531_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Global tenant registry (lives in the public schema). One row per licitación; maps a
    # human-facing licitación to its isolated storage: a PostgreSQL schema, a Milvus collection,
    # a MinIO key prefix (= slug), and a Redis key namespace (= slug).
    #
    # Guarded against "already exists": the dashboard's init_db runs Base.metadata.create_all on
    # startup against the same (Neon) database, so the table may already exist when this migration
    # runs. create_table is therefore conditional, and the seed is insert-if-absent.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "licitaciones" not in inspector.get_table_names():
        op.create_table(
            "licitaciones",
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False, unique=True),
            sa.Column("slug", sa.String(255), nullable=False, unique=True),
            sa.Column("source_path", sa.String(1024), nullable=False, server_default=""),
            sa.Column("schema_name", sa.String(255), nullable=False),
            sa.Column("milvus_collection", sa.String(255), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text("now()"),
            ),
        )

    # Seed the pre-existing single-tenant corpus as the "Laboratorios Calidad" licitación, mapped to
    # the current public schema + rag_documents collection (zero data movement). source_path='' means
    # the LOCAL_SOURCE_FOLDER root (its current ingestion scope). Insert only when absent.
    existing = bind.execute(
        sa.text("SELECT 1 FROM licitaciones WHERE slug = :slug"),
        {"slug": "laboratorios_calidad"},
    ).first()
    if not existing:
        op.execute(
            sa.text(
                "INSERT INTO licitaciones "
                "(id, name, slug, source_path, schema_name, milvus_collection, status) "
                "VALUES (:id, :name, :slug, :source_path, :schema_name, :milvus_collection, 'active')"
            ).bindparams(
                id="00000000-0000-0000-0000-000000000001",
                name="Laboratorios Calidad",
                slug="laboratorios_calidad",
                source_path="",
                schema_name="public",
                milvus_collection="rag_documents",
            )
        )


def downgrade() -> None:
    op.drop_table("licitaciones")
