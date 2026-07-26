"""Add deterministic daily reading lists.

Revision ID: 20260725_02
Revises: 20260724_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_02"
down_revision: str | None = "20260724_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("language", sa.String(12)))
    op.add_column("articles", sa.Column("content_type", sa.String(30)))

    op.create_table(
        "daily_reading_lists",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("list_date", sa.Date(), nullable=False, unique=True),
        sa.Column("target_article_count", sa.Integer(), nullable=False),
        sa.Column("target_reading_minutes", sa.Integer(), nullable=False),
        sa.Column("actual_article_count", sa.Integer(), nullable=False),
        sa.Column("actual_reading_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('building', 'complete', 'failed')",
            name="ck_daily_reading_lists_status",
        ),
    )
    op.create_table(
        "daily_reading_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "reading_list_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_reading_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.BigInteger(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("topic_score", sa.Float(), nullable=False),
        sa.Column("source_score", sa.Float(), nullable=False),
        sa.Column("length_score", sa.Float(), nullable=False),
        sa.Column("reading_minutes", sa.Integer(), nullable=False),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "reading_list_id", "article_id", name="uq_daily_reading_item_article"
        ),
        sa.UniqueConstraint(
            "reading_list_id", "rank", name="uq_daily_reading_item_rank"
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_reading_items")
    op.drop_table("daily_reading_lists")
    op.drop_column("articles", "content_type")
    op.drop_column("articles", "language")
