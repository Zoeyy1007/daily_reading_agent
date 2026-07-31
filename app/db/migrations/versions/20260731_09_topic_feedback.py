"""Add explicit topic feedback and case-insensitive login uniqueness.

Revision ID: 20260731_09
Revises: 20260731_08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_09"
down_revision: str | None = "20260731_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = (
    "'too_long', 'too_repetitive', 'strong_evidence', 'good_writing', "
    "'not_interested', 'too_technical', 'topic_technology', "
    "'topic_artificial_intelligence', 'topic_science', 'topic_business', "
    "'topic_politics', 'topic_health', 'topic_climate', 'topic_sports', "
    "'topic_culture', 'topic_crime'"
)


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_users_login_id_normalized "
        "ON users (lower(login_id)) WHERE login_id IS NOT NULL"
    )
    op.drop_constraint(
        "ck_feedback_events_reason", "feedback_events", type_="check"
    )
    op.create_check_constraint(
        "ck_feedback_events_reason",
        "feedback_events",
        f"reason IS NULL OR reason IN ({REASONS})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_feedback_events_reason", "feedback_events", type_="check"
    )
    op.create_check_constraint(
        "ck_feedback_events_reason",
        "feedback_events",
        "reason IS NULL OR reason IN ('too_long', 'too_repetitive', "
        "'strong_evidence', 'good_writing', 'not_interested', 'too_technical')",
    )
    op.drop_index("uq_users_login_id_normalized", table_name="users")
