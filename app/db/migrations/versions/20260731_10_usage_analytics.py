"""Add privacy-conscious website usage events.

Revision ID: 20260731_10
Revises: 20260731_09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_10"
down_revision: str | None = "20260731_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("visitor_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("path", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('page_view')",
            name="ck_usage_events_type",
        ),
    )
    op.create_index("ix_usage_events_created", "usage_events", ["created_at"])
    op.create_index(
        "ix_usage_events_visitor_created",
        "usage_events",
        ["visitor_hash", "created_at"],
    )
    op.create_index(
        "ix_usage_events_user_created",
        "usage_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_user_created", table_name="usage_events")
    op.drop_index("ix_usage_events_visitor_created", table_name="usage_events")
    op.drop_index("ix_usage_events_created", table_name="usage_events")
    op.drop_table("usage_events")
