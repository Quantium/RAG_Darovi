"""add chat_interactions table

Revision ID: 20260525_0004
Revises: 20260524_0003
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0004"
down_revision = "20260524_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_interactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("rating", sa.String(8), nullable=True),
        sa.Column("correction", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_interactions")
