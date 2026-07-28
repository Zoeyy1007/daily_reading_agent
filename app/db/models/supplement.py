from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.article import Article
    from app.db.models.daily_reading import DailyReadingItem
    from app.db.models.evidence import ArticleChunk


class SupplementStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"


class SupplementRun(Base):
    __tablename__ = "supplement_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'skipped', "
            "'insufficient', 'failed')",
            name="ck_supplement_runs_status",
        ),
        Index("ix_supplement_runs_daily_run", "daily_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    daily_reading_item_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reading_items.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    daily_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), default=SupplementStatus.QUEUED.value, nullable=False
    )
    detected_gaps: Mapped[str | None] = mapped_column(Text)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    tool_history: Mapped[str | None] = mapped_column(Text)
    original_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    daily_reading_item: Mapped["DailyReadingItem"] = relationship(
        back_populates="supplement_run"
    )
    evidence_items: Mapped[list["SupplementEvidenceItem"]] = relationship(
        back_populates="supplement_run", cascade="all, delete-orphan"
    )
    cards: Mapped[list["SupplementCard"]] = relationship(
        back_populates="supplement_run",
        cascade="all, delete-orphan",
        order_by="SupplementCard.display_order",
    )


class SupplementEvidenceItem(Base):
    __tablename__ = "supplement_evidence_items"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('local_article', 'web', 'government')",
            name="ck_supplement_evidence_source_type",
        ),
        CheckConstraint(
            "reliability_status IN ('trusted', 'rejected')",
            name="ck_supplement_evidence_reliability",
        ),
        UniqueConstraint(
            "supplement_run_id", "content_hash", name="uq_supplement_evidence_content"
        ),
        Index("ix_supplement_evidence_run", "supplement_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplement_run_id: Mapped[int] = mapped_column(
        ForeignKey("supplement_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL")
    )
    source_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("article_chunks.id", ondelete="SET NULL")
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_score: Mapped[float] = mapped_column(Float, nullable=False)
    reliability_status: Mapped[str] = mapped_column(String(20), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(120))
    agency: Mapped[str | None] = mapped_column(String(300))
    document_type: Mapped[str | None] = mapped_column(String(120))
    document_identifier: Mapped[str | None] = mapped_column(String(200))
    effective_date: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplement_run: Mapped["SupplementRun"] = relationship(
        back_populates="evidence_items"
    )
    source_article: Mapped["Article | None"] = relationship()
    source_chunk: Mapped["ArticleChunk | None"] = relationship()
    citations: Mapped[list["SupplementCardCitation"]] = relationship(
        back_populates="evidence_item"
    )


class SupplementCard(Base):
    __tablename__ = "supplement_cards"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'rejected')",
            name="ck_supplement_cards_verification",
        ),
        UniqueConstraint(
            "supplement_run_id", "display_order", name="uq_supplement_card_order"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplement_run_id: Mapped[int] = mapped_column(
        ForeignKey("supplement_runs.id", ondelete="CASCADE"), nullable=False
    )
    card_type: Mapped[str] = mapped_column(String(40), nullable=False)
    heading: Mapped[str] = mapped_column(String(200), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplement_run: Mapped["SupplementRun"] = relationship(back_populates="cards")
    citations: Mapped[list["SupplementCardCitation"]] = relationship(
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="SupplementCardCitation.statement_index, SupplementCardCitation.citation_order",
    )


class SupplementCardCitation(Base):
    __tablename__ = "supplement_card_citations"
    __table_args__ = (
        UniqueConstraint(
            "card_id",
            "statement_index",
            "evidence_item_id",
            name="uq_supplement_card_statement_evidence",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("supplement_cards.id", ondelete="CASCADE"), nullable=False
    )
    evidence_item_id: Mapped[int] = mapped_column(
        ForeignKey("supplement_evidence_items.id", ondelete="CASCADE"), nullable=False
    )
    statement_index: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    card: Mapped["SupplementCard"] = relationship(back_populates="citations")
    evidence_item: Mapped["SupplementEvidenceItem"] = relationship(
        back_populates="citations"
    )
