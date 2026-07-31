from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.agent_run import DailyRun
    from app.db.models.daily_reading import DailyReadingList
    from app.db.models.feedback import FeedbackEvent, PreferenceFeature, SavedArticle


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "daily_list_length BETWEEN 1 AND 10",
            name="ck_users_daily_list_length",
        ),
        CheckConstraint(
            "expected_reading_minutes_per_article BETWEEN 2 AND 25",
            name="ck_users_expected_article_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    login_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    daily_list_length: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5", nullable=False
    )
    expected_reading_minutes_per_article: Mapped[int] = mapped_column(
        Integer, default=6, server_default="6", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    daily_reading_lists: Mapped[list["DailyReadingList"]] = relationship(
        back_populates="user"
    )
    feedback_events: Mapped[list["FeedbackEvent"]] = relationship(back_populates="user")
    saved_articles: Mapped[list["SavedArticle"]] = relationship(back_populates="user")
    preference_features: Mapped[list["PreferenceFeature"]] = relationship(
        back_populates="user"
    )
    daily_runs: Mapped[list["DailyRun"]] = relationship(back_populates="user")
    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_token_hash", "token_hash", unique=True),
        Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="auth_sessions")


Index(
    "uq_users_login_id_normalized",
    func.lower(User.login_id),
    unique=True,
    postgresql_where=User.login_id.is_not(None),
)
