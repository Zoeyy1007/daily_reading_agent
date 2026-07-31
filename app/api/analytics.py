from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_optional_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.analytics import (
    UsageEventCreate,
    UsageEventReceipt,
    UsageSummaryRead,
)
from app.services.analytics_service import record_usage_event, usage_summary

router = APIRouter(prefix="/analytics", tags=["analytics"])
DBSession = Annotated[Session, Depends(get_db)]
OptionalUser = Annotated[User | None, Depends(get_optional_current_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/events", response_model=UsageEventReceipt, status_code=201)
def create_usage_event(
    payload: UsageEventCreate,
    session: DBSession,
    user: OptionalUser,
) -> UsageEventReceipt:
    recorded = record_usage_event(
        session,
        visitor_id=payload.visitor_id,
        event_type=payload.event_type,
        path=payload.path,
        user_id=user.id if user else None,
        settings=get_settings(),
    )
    return UsageEventReceipt(recorded=recorded)


@router.get("/summary", response_model=UsageSummaryRead)
def get_usage_summary(
    session: DBSession,
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
) -> UsageSummaryRead:
    settings = get_settings()
    if (user.login_id or "").casefold() not in settings.analytics_admin_login_id_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usage metrics are restricted to analytics administrators",
        )
    return usage_summary(session, days=days)
