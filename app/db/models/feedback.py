from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.article import Article
    from app.db.models.user import User


class FeedbackEventType(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"
    SKIP = "skip"
    OPEN = "open"
    COMPLETE = "complete"
    STAR = "star"
    UNSTAR = "unstar"


class FeedbackReason(StrEnum):
    TOO_LONG = "too_long"
    TOO_REPETITIVE = "too_repetitive"
    STRONG_EVIDENCE = "strong_evidence"
    GOOD_WRITING = "good_writing"
    NOT_INTERESTED = "not_interested"
    TOO_TECHNICAL = "too_technical"
    TOPIC_TECHNOLOGY = "topic_technology"
    TOPIC_ARTIFICIAL_INTELLIGENCE = "topic_artificial_intelligence"
    TOPIC_SCIENCE = "topic_science"
    TOPIC_BUSINESS = "topic_business"
    TOPIC_POLITICS = "topic_politics"
    TOPIC_HEALTH = "topic_health"
    TOPIC_CLIMATE = "topic_climate"
    TOPIC_SPORTS = "topic_sports"
    TOPIC_CULTURE = "topic_culture"
    TOPIC_CRIME = "topic_crime"


class ArticleFeatureType(StrEnum):
    SOURCE = "source"
    PUBLISHER = "publisher"
    CATEGORY = "category"
    CONTENT_TYPE = "content_type"
    TOPIC = "topic"


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('like', 'dislike', 'skip', 'open', 'complete', 'star', 'unstar')",
            name="ck_feedback_events_type",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN ('too_long', 'too_repetitive', 'strong_evidence', "
            "'good_writing', 'not_interested', 'too_technical', "
            "'topic_technology', 'topic_artificial_intelligence', 'topic_science', "
            "'topic_business', 'topic_politics', 'topic_health', 'topic_climate', "
            "'topic_sports', 'topic_culture', 'topic_crime')",
            name="ck_feedback_events_reason",
        ),
        Index("ix_feedback_events_user_created", "user_id", "created_at"),
        Index("ix_feedback_events_article", "article_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="feedback_events")
    article: Mapped["Article"] = relationship(back_populates="feedback_events")


class SavedArticle(Base):
    __tablename__ = "saved_articles"
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_saved_articles_user_article"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE")
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="saved_articles")
    article: Mapped["Article"] = relationship(back_populates="saved_by_users")


class ArticleFeature(Base):
    __tablename__ = "article_features"
    __table_args__ = (
        UniqueConstraint(
            "article_id", "feature_type", "feature_value", name="uq_article_feature"
        ),
        Index("ix_article_features_lookup", "feature_type", "feature_value"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE")
    )
    feature_type: Mapped[str] = mapped_column(String(30))
    feature_value: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    article: Mapped["Article"] = relationship(back_populates="features")


class PreferenceFeature(Base):
    __tablename__ = "preference_features"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "feature_type", "feature_value", name="uq_preference_feature"
        ),
        Index("ix_preference_features_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    feature_type: Mapped[str] = mapped_column(String(30))
    feature_value: Mapped[str] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    positive_count: Mapped[int] = mapped_column(default=0)
    negative_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="preference_features")
