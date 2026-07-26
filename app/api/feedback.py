from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_current_user_id
from app.db.models import FeedbackEvent, PreferenceFeature, SavedArticle
from app.db.session import get_db
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackRead,
    PreferenceFeatureRead,
    SavedArticleRead,
)
from app.services.feedback_service import record_feedback

router = APIRouter(tags=["feedback"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUserID = Annotated[int, Depends(get_current_user_id)]


@router.post(
    "/articles/{article_id}/feedback",
    response_model=FeedbackRead,
    status_code=201,
)
def create_feedback(
    article_id: int,
    payload: FeedbackCreate,
    session: DBSession,
    user_id: CurrentUserID,
) -> FeedbackEvent:
    try:
        return record_feedback(
            session,
            user_id=user_id,
            article_id=article_id,
            event_type=payload.event_type.value,
            reason=payload.reason.value if payload.reason else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/feedback", response_model=list[FeedbackRead])
def list_feedback(
    session: DBSession,
    user_id: CurrentUserID,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FeedbackEvent]:
    return list(
        session.scalars(
            select(FeedbackEvent)
            .where(FeedbackEvent.user_id == user_id)
            .order_by(FeedbackEvent.created_at.desc(), FeedbackEvent.id.desc())
            .limit(limit)
        )
    )


@router.get("/saved-articles", response_model=list[SavedArticleRead])
def list_saved_articles(
    session: DBSession,
    user_id: CurrentUserID,
) -> list[SavedArticle]:
    return list(
        session.scalars(
            select(SavedArticle)
            .where(SavedArticle.user_id == user_id)
            .options(selectinload(SavedArticle.article))
            .order_by(SavedArticle.saved_at.desc())
        )
    )


@router.get("/preferences/derived", response_model=list[PreferenceFeatureRead])
def list_derived_preferences(
    session: DBSession,
    user_id: CurrentUserID,
) -> list[PreferenceFeature]:
    return list(
        session.scalars(
            select(PreferenceFeature)
            .where(PreferenceFeature.user_id == user_id)
            .order_by(
                PreferenceFeature.confidence.desc(),
                PreferenceFeature.score.desc(),
            )
        )
    )
