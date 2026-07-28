"""Add source-grounded supplemental evidence and cards.

Revision ID: 20260727_07
Revises: 20260726_06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_07"
down_revision: str | None = "20260726_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplement_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "daily_reading_item_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_reading_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "daily_run_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("detected_gaps", sa.Text()),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("tool_history", sa.Text()),
        sa.Column("original_word_count", sa.Integer(), nullable=False),
        sa.Column("word_budget", sa.Integer(), nullable=False),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'skipped', 'insufficient', 'failed')",
            name="ck_supplement_runs_status",
        ),
    )
    op.create_index("ix_supplement_runs_daily_run", "supplement_runs", ["daily_run_id"])

    op.create_table(
        "supplement_evidence_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "supplement_run_id",
            sa.BigInteger(),
            sa.ForeignKey("supplement_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="SET NULL")),
        sa.Column("source_chunk_id", sa.BigInteger(), sa.ForeignKey("article_chunks.id", ondelete="SET NULL")),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(300), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=False),
        sa.Column("reliability_status", sa.String(20), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("jurisdiction", sa.String(120)),
        sa.Column("agency", sa.String(300)),
        sa.Column("document_type", sa.String(120)),
        sa.Column("document_identifier", sa.String(200)),
        sa.Column("effective_date", sa.Date()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source_type IN ('local_article', 'web', 'government')",
            name="ck_supplement_evidence_source_type",
        ),
        sa.CheckConstraint(
            "reliability_status IN ('trusted', 'rejected')",
            name="ck_supplement_evidence_reliability",
        ),
        sa.UniqueConstraint(
            "supplement_run_id", "content_hash", name="uq_supplement_evidence_content"
        ),
    )
    op.create_index(
        "ix_supplement_evidence_run", "supplement_evidence_items", ["supplement_run_id"]
    )

    op.create_table(
        "supplement_cards",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "supplement_run_id",
            sa.BigInteger(),
            sa.ForeignKey("supplement_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_type", sa.String(40), nullable=False),
        sa.Column("heading", sa.String(200), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'rejected')",
            name="ck_supplement_cards_verification",
        ),
        sa.UniqueConstraint(
            "supplement_run_id", "display_order", name="uq_supplement_card_order"
        ),
    )

    op.create_table(
        "supplement_card_citations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("card_id", sa.BigInteger(), sa.ForeignKey("supplement_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "evidence_item_id",
            sa.BigInteger(),
            sa.ForeignKey("supplement_evidence_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement_index", sa.Integer(), nullable=False),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("statement_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "card_id",
            "statement_index",
            "evidence_item_id",
            name="uq_supplement_card_statement_evidence",
        ),
    )


def downgrade() -> None:
    op.drop_table("supplement_card_citations")
    op.drop_table("supplement_cards")
    op.drop_index("ix_supplement_evidence_run", table_name="supplement_evidence_items")
    op.drop_table("supplement_evidence_items")
    op.drop_index("ix_supplement_runs_daily_run", table_name="supplement_runs")
    op.drop_table("supplement_runs")
