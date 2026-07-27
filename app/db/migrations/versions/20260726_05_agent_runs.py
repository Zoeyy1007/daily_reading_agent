"""Add stateful agent run and event records.

Revision ID: 20260726_05
Revises: 20260726_04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_05"
down_revision: str | None = "20260726_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column(
            "duplicate_of_article_id",
            sa.BigInteger(),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
        ),
    )
    op.create_table(
        "daily_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("thread_id", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("list_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_node", sa.String(60)),
        sa.Column("expansion_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_expansion_rounds", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reading_list_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_reading_lists.id", ondelete="SET NULL"),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')",
            name="ck_daily_runs_status",
        ),
    )
    op.create_index("ix_daily_runs_user_created", "daily_runs", ["user_id", "created_at"])
    op.create_index("ix_daily_runs_status", "daily_runs", ["status"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(60), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("elapsed_ms", sa.Float()),
        sa.Column("message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'complete', 'failed', 'skipped')",
            name="ck_run_events_status",
        ),
        sa.UniqueConstraint("run_id", "node_name", "attempt", name="uq_run_event_attempt"),
    )
    op.create_index("ix_run_events_run_created", "run_events", ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("daily_runs")
    op.drop_column("articles", "duplicate_of_article_id")
