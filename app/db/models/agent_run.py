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
    from app.db.models.user import User


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class RunEventStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class DailyRun(Base):
    __tablename__ = "daily_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')",
            name="ck_daily_runs_status",
        ),
        Index("ix_daily_runs_user_created", "user_id", "created_at"),
        Index("ix_daily_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    list_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=AgentRunStatus.QUEUED.value, nullable=False
    )
    current_node: Mapped[str | None] = mapped_column(String(60))
    expansion_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_expansion_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reading_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_reading_lists.id", ondelete="SET NULL")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="daily_runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.id"
    )


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'complete', 'failed', 'skipped')",
            name="ck_run_events_status",
        ),
        UniqueConstraint("run_id", "node_name", "attempt", name="uq_run_event_attempt"),
        Index("ix_run_events_run_created", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("daily_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_name: Mapped[str] = mapped_column(String(60), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["DailyRun"] = relationship(back_populates="events")
