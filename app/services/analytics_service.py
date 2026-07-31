import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import UsageEvent
from app.schemas.analytics import DailyUsageRead, UsageSummaryRead


def hash_visitor_id(visitor_id: UUID) -> str:
    return hashlib.sha256(str(visitor_id).encode("ascii")).hexdigest()


def record_usage_event(
    session: Session,
    *,
    visitor_id: UUID,
    event_type: str,
    path: str,
    user_id: int | None,
    settings: Settings,
) -> bool:
    if not settings.analytics_enabled:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=settings.analytics_retention_days)
    session.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff))
    session.add(
        UsageEvent(
            user_id=user_id,
            visitor_hash=hash_visitor_id(visitor_id),
            event_type=event_type,
            path=path,
        )
    )
    session.commit()
    return True


def usage_summary(session: Session, *, days: int) -> UsageSummaryRead:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    totals = session.execute(
        select(
            func.count(UsageEvent.id),
            func.count(func.distinct(UsageEvent.visitor_hash)),
            func.count(func.distinct(UsageEvent.user_id)),
        ).where(
            UsageEvent.event_type == "page_view",
            UsageEvent.created_at >= cutoff,
        )
    ).one()
    event_day = cast(UsageEvent.created_at, Date).label("event_day")
    daily_rows = session.execute(
        select(
            event_day,
            func.count(UsageEvent.id),
            func.count(func.distinct(UsageEvent.visitor_hash)),
            func.count(func.distinct(UsageEvent.user_id)),
        )
        .where(
            UsageEvent.event_type == "page_view",
            UsageEvent.created_at >= cutoff,
        )
        .group_by(event_day)
        .order_by(event_day)
    ).all()
    return UsageSummaryRead(
        days=days,
        total_page_views=int(totals[0] or 0),
        unique_visitors=int(totals[1] or 0),
        signed_in_users=int(totals[2] or 0),
        daily=[
            DailyUsageRead(
                day=row[0],
                page_views=int(row[1]),
                unique_visitors=int(row[2]),
                signed_in_users=int(row[3]),
            )
            for row in daily_rows
        ],
    )
