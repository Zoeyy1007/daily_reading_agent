"""Tighten per-user reading preference limits.

Revision ID: 20260731_12
Revises: 20260731_11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_12"
down_revision: str | None = "20260731_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET daily_list_length = "
        "LEAST(GREATEST(daily_list_length, 1), 10)"
    )
    op.execute(
        "UPDATE users SET expected_reading_minutes_per_article = "
        "LEAST(GREATEST(expected_reading_minutes_per_article, 2), 25)"
    )
    op.drop_constraint("ck_users_daily_list_length", "users", type_="check")
    op.drop_constraint(
        "ck_users_expected_article_minutes", "users", type_="check"
    )
    op.create_check_constraint(
        "ck_users_daily_list_length",
        "users",
        "daily_list_length BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "ck_users_expected_article_minutes",
        "users",
        "expected_reading_minutes_per_article BETWEEN 2 AND 25",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_expected_article_minutes", "users", type_="check"
    )
    op.drop_constraint("ck_users_daily_list_length", "users", type_="check")
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
