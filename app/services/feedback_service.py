import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Article,
    FeedbackEvent,
    FeedbackEventType,
    SavedArticle,
    User,
)
from app.services.article_feature_service import ensure_article_features
from app.services.preference_service import rebuild_preference_features
from app.utils.timing import timed_stage

logger = logging.getLogger("daily_reading.feedback")


def record_feedback(
    session: Session,
    *,
    user_id: int,
    article_id: int,
    event_type: str,
    reason: str | None,
) -> FeedbackEvent:
    with timed_stage(
        logger,
        "feedback.total",
        user_id=user_id,
        article_id=article_id,
        event_type=event_type,
    ):
        if session.get(User, user_id) is None:
            raise LookupError(f"User {user_id} does not exist")
        article = session.get(Article, article_id)
        if article is None:
            raise LookupError(f"Article {article_id} does not exist")

        event = FeedbackEvent(
            user_id=user_id,
            article_id=article_id,
            event_type=event_type,
            reason=reason,
        )
        session.add(event)
        with timed_stage(logger, "feedback.update_saved_state"):
            saved = session.scalar(
                select(SavedArticle).where(
                    SavedArticle.user_id == user_id,
                    SavedArticle.article_id == article_id,
                )
            )
            if event_type == FeedbackEventType.STAR.value and saved is None:
                session.add(SavedArticle(user_id=user_id, article_id=article_id))
            elif event_type == FeedbackEventType.UNSTAR.value and saved is not None:
                session.delete(saved)

        with timed_stage(logger, "feedback.ensure_article_features"):
            ensure_article_features(session, [article])
        with timed_stage(logger, "feedback.rebuild_preferences"):
            rebuild_preference_features(session, user_id)
        session.commit()
        session.refresh(event)
        return event
