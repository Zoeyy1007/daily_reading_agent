"""Add Phase 5 embeddings, story clusters, claims, and evidence.

Revision ID: 20260726_06
Revises: 20260726_05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260726_06"
down_revision: str | None = "20260726_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("articles", sa.Column("embedding", Vector(1024)))
    op.add_column("articles", sa.Column("embedding_model", sa.String(120)))
    op.add_column("articles", sa.Column("embedded_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_articles_embedding_hnsw",
        "articles",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "article_ai_classifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("content_type", sa.String(30), nullable=False),
        sa.Column("is_news", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "story_clusters",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("representative_title", sa.Text(), nullable=False),
        sa.Column("event_summary", sa.Text()),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("centroid_embedding", Vector(1024), nullable=False),
        sa.Column("representative_article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="SET NULL")),
        sa.Column("comparison_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_story_clusters_event_date", "story_clusters", ["event_date"])
    op.create_index(
        "ix_story_clusters_embedding_hnsw",
        "story_clusters",
        ["centroid_embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"centroid_embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "story_cluster_members",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cluster_id", sa.BigInteger(), sa.ForeignKey("story_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False, server_default="coverage"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("article_id", name="uq_story_cluster_member_article"),
        sa.UniqueConstraint("cluster_id", "article_id", name="uq_story_cluster_member"),
    )

    op.create_table(
        "article_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text()),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("character_start", sa.Integer(), nullable=False),
        sa.Column("character_end", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("article_id", "chunk_index", name="uq_article_chunk_index"),
    )
    op.create_index("ix_article_chunks_article", "article_chunks", ["article_id"])
    op.create_index(
        "ix_article_chunks_embedding_hnsw",
        "article_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "article_claims",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), sa.ForeignKey("story_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=False),
        sa.Column("claim_type", sa.String(40), nullable=False),
        sa.Column("supporting_excerpt", sa.Text(), nullable=False),
        sa.Column("attribution", sa.Text()),
        sa.Column("primary_source_url", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("article_id", "claim_hash", name="uq_article_claim_hash"),
    )
    op.create_index("ix_article_claims_cluster", "article_claims", ["cluster_id"])
    op.create_index(
        "ix_article_claims_embedding_hnsw",
        "article_claims",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "claim_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cluster_id", sa.BigInteger(), sa.ForeignKey("story_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("left_claim_id", sa.BigInteger(), sa.ForeignKey("article_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("right_claim_id", sa.BigInteger(), sa.ForeignKey("article_claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("left_claim_id", "right_claim_id", name="uq_claim_link_pair"),
    )
    op.create_index("ix_claim_links_cluster", "claim_links", ["cluster_id"])

    op.create_table(
        "cluster_comparisons",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cluster_id", sa.BigInteger(), sa.ForeignKey("story_clusters.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("representative_article_id", sa.BigInteger(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shared_claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disputed_claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsupported_claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("daily_runs.id", ondelete="SET NULL")),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("elapsed_ms", sa.Float()),
        sa.Column("error", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_model_calls_run_role", "model_calls", ["run_id", "role"])
    op.create_index("ix_model_calls_created", "model_calls", ["created_at"])


def downgrade() -> None:
    op.drop_table("model_calls")
    op.drop_table("cluster_comparisons")
    op.drop_table("claim_links")
    op.drop_table("article_claims")
    op.drop_table("article_chunks")
    op.drop_table("story_cluster_members")
    op.drop_table("story_clusters")
    op.drop_table("article_ai_classifications")
    op.drop_index("ix_articles_embedding_hnsw", table_name="articles")
    op.drop_column("articles", "embedded_at")
    op.drop_column("articles", "embedding_model")
    op.drop_column("articles", "embedding")
