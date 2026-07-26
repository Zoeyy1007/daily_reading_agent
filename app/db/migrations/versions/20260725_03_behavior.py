"""Add user-scoped feedback and behavioral preferences.

Revision ID: 20260725_03
Revises: 20260725_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_03"
down_revision: str | None = "20260725_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(255), unique=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.bulk_insert(users, [{"id": 1, "display_name": "Local User", "is_active": True}])
    op.execute("SELECT setval('users_id_seq', 1, true)")

    op.drop_constraint("daily_reading_lists_list_date_key", "daily_reading_lists", type_="unique")
    op.add_column("daily_reading_lists", sa.Column("user_id", sa.BigInteger()))
    op.execute("UPDATE daily_reading_lists SET user_id = 1")
    op.alter_column("daily_reading_lists", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_daily_reading_lists_user",
        "daily_reading_lists",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_daily_reading_list_user_date", "daily_reading_lists", ["user_id", "list_date"]
    )

    op.add_column("daily_reading_items", sa.Column("base_score", sa.Float()))
    op.add_column(
        "daily_reading_items",
        sa.Column("personalization_score", sa.Float(), server_default="0", nullable=False),
    )
    op.execute("UPDATE daily_reading_items SET base_score = total_score")
    op.alter_column("daily_reading_items", "base_score", nullable=False)

    op.create_table(
        "feedback_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('like', 'dislike', 'skip', 'open', 'complete', 'star', 'unstar')",
            name="ck_feedback_events_type",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('too_long', 'too_repetitive', 'strong_evidence', "
            "'good_writing', 'not_interested', 'too_technical')",
            name="ck_feedback_events_reason",
        ),
    )
    op.create_index("ix_feedback_events_user_created", "feedback_events", ["user_id", "created_at"])
    op.create_index("ix_feedback_events_article", "feedback_events", ["article_id"])

    op.create_table(
        "saved_articles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "article_id", name="uq_saved_articles_user_article"),
    )

    op.create_table(
        "article_features",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_type", sa.String(30), nullable=False),
        sa.Column("feature_value", sa.String(200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("article_id", "feature_type", "feature_value", name="uq_article_feature"),
    )
    op.create_index("ix_article_features_lookup", "article_features", ["feature_type", "feature_value"])

    op.create_table(
        "preference_features",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_type", sa.String(30), nullable=False),
        sa.Column("feature_value", sa.String(200), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("positive_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "feature_type", "feature_value", name="uq_preference_feature"),
    )
    op.create_index("ix_preference_features_user", "preference_features", ["user_id"])


def downgrade() -> None:
    op.drop_table("preference_features")
    op.drop_table("article_features")
    op.drop_table("saved_articles")
    op.drop_table("feedback_events")
    op.drop_column("daily_reading_items", "personalization_score")
    op.drop_column("daily_reading_items", "base_score")
    op.drop_constraint("uq_daily_reading_list_user_date", "daily_reading_lists", type_="unique")
    op.drop_constraint("fk_daily_reading_lists_user", "daily_reading_lists", type_="foreignkey")
    op.drop_column("daily_reading_lists", "user_id")
    op.create_unique_constraint(
        "daily_reading_lists_list_date_key", "daily_reading_lists", ["list_date"]
    )
    op.drop_table("users")
