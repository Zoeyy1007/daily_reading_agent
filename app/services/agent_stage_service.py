from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.state import CandidateScore
from app.config import Settings
from app.db.models import (
    Article,
    ArticleStatus,
    DailyReadingItem,
    DailyReadingList,
    DailyReadingStatus,
    PreferenceFeature,
)
from app.services.article_feature_service import ensure_article_features
from app.services.classification_service import enrich_article
from app.services.filter_service import filter_article
from app.services.personalization_service import preference_index, score_personalization
from app.services.reading_list_service import get_daily_reading_list
from app.services.scoring_service import score_article
from app.utils.article_metrics import calculate_reading_minutes


def _load_articles(session: Session, article_ids: list[int]) -> list[Article]:
    if not article_ids:
        return []
    return list(
        session.scalars(
            select(Article)
            .where(Article.id.in_(article_ids))
            .options(selectinload(Article.source))
            .order_by(Article.id)
        )
    )


def classify_article_ids(session: Session, article_ids: list[int]) -> int:
    articles = _load_articles(session, article_ids)
    for article in articles:
        enrich_article(article)
    session.commit()
    return len(articles)


def filter_article_ids(
    session: Session,
    article_ids: list[int],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[list[int], dict[str, int]]:
    current_time = now or datetime.now(UTC)
    accepted: list[int] = []
    rejection_counts: dict[str, int] = {}
    for article in _load_articles(session, article_ids):
        result = filter_article(article, settings, now=current_time)
        if result.accepted:
            accepted.append(article.id)
        for reason in result.reasons:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    return accepted, rejection_counts


def score_article_ids(
    session: Session,
    article_ids: list[int],
    user_id: int,
    settings: Settings,
    *,
    now: datetime | None = None,
    target_article_reading_minutes: int | None = None,
) -> list[CandidateScore]:
    current_time = now or datetime.now(UTC)
    articles = _load_articles(session, article_ids)
    features_by_article = ensure_article_features(session, articles)
    preferences = list(
        session.scalars(
            select(PreferenceFeature).where(PreferenceFeature.user_id == user_id)
        )
    )
    preferences_by_feature = preference_index(preferences)
    results: list[CandidateScore] = []
    for article in articles:
        base = score_article(
            article,
            settings,
            now=current_time,
            expected_reading_minutes=target_article_reading_minutes,
        )
        personal = score_personalization(
            features_by_article[article.id], preferences_by_feature, settings
        )
        personal_reasons = "; ".join(personal.reasons)
        reason = base.reason
        if personal_reasons:
            reason += f"; personalization: {personal_reasons}"
        results.append(
            CandidateScore(
                article_id=article.id,
                total_score=round(base.total + personal.score, 2),
                base_score=base.total,
                personalization_score=personal.score,
                freshness_score=base.freshness,
                topic_score=base.topic,
                source_score=base.source,
                length_score=base.length,
                reading_minutes=calculate_reading_minutes(
                    article.word_count or 0, settings.reading_words_per_minute
                ),
                selection_reason=reason,
            )
        )
    session.commit()
    return sorted(results, key=lambda item: item["total_score"], reverse=True)


def select_scored_articles(
    scores: list[CandidateScore], target_count: int, target_minutes: int
) -> list[CandidateScore]:
    selected: list[CandidateScore] = []
    total_minutes = 0
    for candidate in scores:
        if len(selected) >= target_count:
            break
        reading_minutes = candidate["reading_minutes"]
        if total_minutes + reading_minutes > target_minutes:
            continue
        selected.append(candidate)
        total_minutes += reading_minutes
    return selected


def all_extracted_article_ids(session: Session) -> list[int]:
    return list(
        session.scalars(
            select(Article.id).where(
                Article.status == ArticleStatus.EXTRACTED.value,
                Article.content_text.is_not(None),
            )
        )
    )


def persist_agent_reading_list(
    session: Session,
    *,
    user_id: int,
    list_date: date,
    selected: list[CandidateScore],
    target_article_count: int,
    target_reading_minutes: int,
    regenerate: bool,
) -> DailyReadingList:
    existing = get_daily_reading_list(session, list_date, user_id)
    if existing and not regenerate:
        return existing
    if existing:
        reading_list = existing
        reading_list.items.clear()
        session.flush()
        reading_list.target_article_count = target_article_count
        reading_list.target_reading_minutes = target_reading_minutes
        reading_list.status = DailyReadingStatus.BUILDING.value
    else:
        reading_list = DailyReadingList(
            user_id=user_id,
            list_date=list_date,
            target_article_count=target_article_count,
            target_reading_minutes=target_reading_minutes,
            actual_article_count=0,
            actual_reading_minutes=0,
            status=DailyReadingStatus.BUILDING.value,
        )
        session.add(reading_list)

    articles = {
        article.id: article
        for article in _load_articles(
            session, [candidate["article_id"] for candidate in selected]
        )
    }
    total_minutes = 0
    for rank, candidate in enumerate(selected, start=1):
        article = articles.get(candidate["article_id"])
        if article is None:
            continue
        total_minutes += candidate["reading_minutes"]
        reading_list.items.append(
            DailyReadingItem(
                article=article,
                rank=rank,
                total_score=candidate["total_score"],
                base_score=candidate["base_score"],
                personalization_score=candidate["personalization_score"],
                freshness_score=candidate["freshness_score"],
                topic_score=candidate["topic_score"],
                source_score=candidate["source_score"],
                length_score=candidate["length_score"],
                reading_minutes=candidate["reading_minutes"],
                selection_reason=candidate["selection_reason"],
            )
        )
    reading_list.actual_article_count = len(reading_list.items)
    reading_list.actual_reading_minutes = total_minutes
    reading_list.status = DailyReadingStatus.COMPLETE.value
    session.commit()
    return reading_list
