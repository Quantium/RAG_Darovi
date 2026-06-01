"""add username to chat_interactions

Revision ID: 20260531_0005
Revises: 20260525_0004
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_0005"
down_revision = "20260525_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain string, NO foreign key to chat_users — historical rows must survive user deletion.
    # server_default='admin' backfills all existing rows in a single statement and is kept so the
    # migration stays backward-compatible: the previously-deployed chat service (whose INSERT omits
    # username) keeps working during the deploy window. New code always sets username explicitly.
    op.add_column(
        "chat_interactions",
        sa.Column("username", sa.String(10), nullable=False, server_default="admin"),
    )


def downgrade() -> None:
    op.drop_column("chat_interactions", "username")
