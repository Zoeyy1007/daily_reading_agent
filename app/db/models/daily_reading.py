from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.article import Article
    from app.db.models.user import User


class DailyReadingStatus(StrEnum):
    BUILDING = "building"
    COMPLETE = "complete"
    FAILED = "failed"


class DailyReadingList(Base):
    __tablename__ = "daily_reading_lists"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building', 'complete', 'failed')",
            name="ck_daily_reading_lists_status",
        ),
        UniqueConstraint("user_id", "list_date", name="uq_daily_reading_list_user_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    list_date: Mapped[date] = mapped_column(Date)
    target_article_count: Mapped[int] = mapped_column(Integer)
    target_reading_minutes: Mapped[int] = mapped_column(Integer)
    actual_article_count: Mapped[int] = mapped_column(Integer, default=0)
    actual_reading_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default=DailyReadingStatus.BUILDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["DailyReadingItem"]] = relationship(
        back_populates="reading_list",
        cascade="all, delete-orphan",
        order_by="DailyReadingItem.rank",
    )
    user: Mapped["User"] = relationship(back_populates="daily_reading_lists")


class DailyReadingItem(Base):
    __tablename__ = "daily_reading_items"
    __table_args__ = (
        UniqueConstraint(
            "reading_list_id", "article_id", name="uq_daily_reading_item_article"
        ),
        UniqueConstraint(
            "reading_list_id", "rank", name="uq_daily_reading_item_rank"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reading_list_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reading_lists.id", ondelete="CASCADE")
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE")
    )
    rank: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[float] = mapped_column(Float)
    base_score: Mapped[float] = mapped_column(Float)
    personalization_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float)
    topic_score: Mapped[float] = mapped_column(Float)
    source_score: Mapped[float] = mapped_column(Float)
    length_score: Mapped[float] = mapped_column(Float)
    reading_minutes: Mapped[int] = mapped_column(Integer)
    selection_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    reading_list: Mapped["DailyReadingList"] = relationship(back_populates="items")
    article: Mapped["Article"] = relationship(back_populates="reading_list_items")
