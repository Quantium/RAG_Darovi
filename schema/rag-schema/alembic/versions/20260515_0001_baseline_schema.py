"""baseline schema

Revision ID: 20260515_0001
Revises:
Create Date: 2026-05-15 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260515_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_records",
        sa.Column("drive_file_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("drive_modified_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_processed_at", sa.DateTime(), nullable=True),
        sa.Column("minio_raw_key", sa.String(), nullable=True),
        sa.Column("minio_text_key", sa.String(), nullable=True),
        sa.Column("raw_source_version", sa.String(), nullable=True),
        sa.Column("raw_checksum", sa.String(length=128), nullable=True),
        sa.Column("raw_synced_at", sa.DateTime(), nullable=True),
        sa.Column("raw_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("text_checksum", sa.String(length=128), nullable=True),
        sa.Column("text_source_checksum", sa.String(length=128), nullable=True),
        sa.Column("text_extracted_at", sa.DateTime(), nullable=True),
        sa.Column("text_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("text_error", sa.Text(), nullable=True),
    )

    op.create_table(
        "sync_state",
        sa.Column("key", sa.String(), primary_key=True, nullable=False),
        sa.Column("value", sa.String(), nullable=False, server_default=""),
    )

    op.create_table(
        "drive_connection",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("selected_folder_id", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "extracted_documents",
        sa.Column("drive_file_id", sa.String(), sa.ForeignKey("file_records.drive_file_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_type", sa.String(), nullable=True),
        sa.Column("issuer", sa.String(), nullable=True),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("parties", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("extras", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("extracted_documents")
    op.drop_table("drive_connection")
    op.drop_table("sync_state")
    op.drop_table("file_records")
