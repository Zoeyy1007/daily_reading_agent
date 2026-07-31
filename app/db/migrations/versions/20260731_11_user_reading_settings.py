"""Add per-user reading-list preferences.

Revision ID: 20260731_11
Revises: 20260731_10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_11"
down_revision: str | None = "20260731_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "daily_list_length",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "expected_reading_minutes_per_article",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    op.create_check_constraint(
        "ck_users_daily_list_length",
        "users",
        "daily_list_length BETWEEN 1 AND 20",
    )
    op.create_check_constraint(
        "ck_users_expected_article_minutes",
        "users",
        "expected_reading_minutes_per_article BETWEEN 1 AND 60",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_expected_article_minutes", "users", type_="check"
    )
    op.drop_constraint("ck_users_daily_list_length", "users", type_="check")
    op.drop_column("users", "expected_reading_minutes_per_article")
    op.drop_column("users", "daily_list_length")
