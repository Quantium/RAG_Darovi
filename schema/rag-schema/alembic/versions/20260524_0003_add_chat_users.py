"""add chat_users table

Revision ID: 20260524_0003
Revises: 20260518_0002
Create Date: 2026-05-24 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_users",
        sa.Column("username", sa.String(10), primary_key=True, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_users")
