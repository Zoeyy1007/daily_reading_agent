from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.daily_reading import DailyReadingItem
    from app.db.models.feedback import ArticleFeature, FeedbackEvent, SavedArticle
    from app.db.models.source import Source


class ArticleStatus(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "rss_guid", name="uq_articles_source_guid"),
        CheckConstraint(
            "status IN ('discovered', 'extracting', 'extracted', 'failed', 'duplicate')",
            name="ck_articles_status",
        ),
        Index("ix_articles_source_published", "source_id", "published_at"),
        Index("ix_articles_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    rss_guid: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    canonical_url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    original_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    rss_summary: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    word_count: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(12))
    content_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(
        String(20), default=ArticleStatus.DISCOVERED.value
    )
    extractor_used: Mapped[str | None] = mapped_column(String(40))
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="articles")
    reading_list_items: Mapped[list["DailyReadingItem"]] = relationship(
        back_populates="article"
    )
    feedback_events: Mapped[list["FeedbackEvent"]] = relationship(
        back_populates="article"
    )
    saved_by_users: Mapped[list["SavedArticle"]] = relationship(back_populates="article")
    features: Mapped[list["ArticleFeature"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
