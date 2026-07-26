"""Create Phase 1 sources and articles tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False, unique=True),
        sa.Column("site_url", sa.Text()),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), server_default="30", nullable=False),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rss_guid", sa.Text()),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("canonical_url_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("rss_summary", sa.Text()),
        sa.Column("content_text", sa.Text()),
        sa.Column("author", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("word_count", sa.Integer()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("extractor_used", sa.String(40)),
        sa.Column("extraction_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('discovered', 'extracting', 'extracted', 'failed', 'duplicate')",
            name="ck_articles_status",
        ),
        sa.UniqueConstraint("source_id", "rss_guid", name="uq_articles_source_guid"),
    )
    op.create_index("ix_articles_source_published", "articles", ["source_id", "published_at"])
    op.create_index("ix_articles_status", "articles", ["status"])


def downgrade() -> None:
    op.drop_index("ix_articles_status", table_name="articles")
    op.drop_index("ix_articles_source_published", table_name="articles")
    op.drop_table("articles")
    op.drop_table("sources")
