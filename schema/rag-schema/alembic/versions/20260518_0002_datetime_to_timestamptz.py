"""convert datetime columns to timestamptz

Revision ID: 20260518_0002
Revises: 20260515_0001
Create Date: 2026-05-18 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260518_0002"
down_revision = "20260515_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("file_records", "drive_modified_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=True,
                    postgresql_using="drive_modified_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "last_processed_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=True,
                    postgresql_using="last_processed_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "raw_synced_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=True,
                    postgresql_using="raw_synced_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "text_extracted_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=True,
                    postgresql_using="text_extracted_at AT TIME ZONE 'UTC'")
    op.alter_column("drive_connection", "updated_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=True,
                    postgresql_using="updated_at AT TIME ZONE 'UTC'")
    op.alter_column("extracted_documents", "extracted_at",
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=False,
                    postgresql_using="extracted_at AT TIME ZONE 'UTC'")


def downgrade() -> None:
    op.alter_column("extracted_documents", "extracted_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    postgresql_using="extracted_at AT TIME ZONE 'UTC'")
    op.alter_column("drive_connection", "updated_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="updated_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "text_extracted_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="text_extracted_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "raw_synced_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="raw_synced_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "last_processed_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="last_processed_at AT TIME ZONE 'UTC'")
    op.alter_column("file_records", "drive_modified_at",
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=True,
                    postgresql_using="drive_modified_at AT TIME ZONE 'UTC'")
