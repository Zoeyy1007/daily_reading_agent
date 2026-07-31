import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db.models import (
    Article,
    ArticleStatus,
    DailyReadingItem,
    DailyReadingList,
    DailyReadingStatus,
    PreferenceFeature,
    User,
)
from app.services.article_feature_service import ensure_article_features
from app.services.classification_service import enrich_article
from app.services.filter_service import filter_article
from app.services.personalization_service import (
    PersonalizationResult,
    preference_index,
    score_personalization,
)
from app.services.scoring_service import ScoreResult, score_article
from app.utils.article_metrics import calculate_reading_minutes
from app.utils.timing import timed_stage

logger = logging.getLogger("daily_reading.pipeline")


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    article: Article
    base_score: ScoreResult
    personalization: PersonalizationResult
    reading_minutes: int

    @property
    def total_score(self) -> float:
        return round(self.base_score.total + self.personalization.score, 2)


def local_today(settings: Settings | None = None) -> date:
    current_settings = settings or get_settings()
    return datetime.now(ZoneInfo(current_settings.scheduler_timezone)).date()


def get_daily_reading_list(
    session: Session, list_date: date, user_id: int
) -> DailyReadingList | None:
    return session.scalar(
        select(DailyReadingList)
        .where(
            DailyReadingList.list_date == list_date,
            DailyReadingList.user_id == user_id,
        )
        .options(
            selectinload(DailyReadingList.items).selectinload(DailyReadingItem.article)
        )
    )


def _eligible_candidates(
    session: Session,
    settings: Settings,
    now: datetime,
    user_id: int,
    expected_reading_minutes: int,
) -> list[ScoredCandidate]:
    with timed_stage(logger, "daily.query_candidates", user_id=user_id):
        articles = list(
            session.scalars(
                select(Article).where(
                    Article.status == ArticleStatus.EXTRACTED.value,
                    Article.content_text.is_not(None),
                ).options(selectinload(Article.source))
            )
        )
    eligible_articles: list[Article] = []
    with timed_stage(logger, "daily.classify_and_filter", article_count=len(articles)):
        for article in articles:
            enrich_article(article)
            result = filter_article(article, settings, now=now)
            if result.accepted:
                eligible_articles.append(article)

    with timed_stage(
        logger, "daily.article_features", article_count=len(eligible_articles)
    ):
        features_by_article = ensure_article_features(session, eligible_articles)
    with timed_stage(logger, "daily.load_preferences", user_id=user_id):
        preferences = list(
            session.scalars(
                select(PreferenceFeature).where(PreferenceFeature.user_id == user_id)
            )
        )
        preferences_by_feature = preference_index(preferences)

    candidates: list[ScoredCandidate] = []
    with timed_stage(logger, "daily.score", article_count=len(eligible_articles)):
        for article in eligible_articles:
            candidates.append(
                ScoredCandidate(
                    article=article,
                    base_score=score_article(
                        article,
                        settings,
                        now=now,
                        expected_reading_minutes=expected_reading_minutes,
                    ),
                    personalization=score_personalization(
                        features_by_article[article.id],
                        preferences_by_feature,
                        settings,
                    ),
                    reading_minutes=calculate_reading_minutes(
                        article.word_count or 0, settings.reading_words_per_minute
                    ),
                )
            )
    candidates.sort(
        key=lambda candidate: (
            candidate.total_score,
            candidate.article.published_at or candidate.article.discovered_at,
        ),
        reverse=True,
    )
    return candidates


def generate_daily_reading_list(
    session: Session,
    list_date: date,
    *,
    user_id: int,
    regenerate: bool = False,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> DailyReadingList:
    current_settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    with timed_stage(
        logger,
        "daily.total",
        user_id=user_id,
        list_date=list_date,
        regenerate=regenerate,
    ):
        user = session.get(User, user_id)
        if user is None:
            raise LookupError(f"User {user_id} does not exist")
        target_count = user.daily_list_length
        target_article_minutes = user.expected_reading_minutes_per_article
        target_total_minutes = target_count * target_article_minutes
        existing = get_daily_reading_list(session, list_date, user_id)
        if existing and not regenerate:
            return existing

        if existing:
            reading_list = existing
            reading_list.items.clear()
            session.flush()
            reading_list.target_article_count = target_count
            reading_list.target_reading_minutes = target_total_minutes
            reading_list.status = DailyReadingStatus.BUILDING.value
        else:
            reading_list = DailyReadingList(
                user_id=user_id,
                list_date=list_date,
                target_article_count=target_count,
                target_reading_minutes=target_total_minutes,
                actual_article_count=0,
                actual_reading_minutes=0,
                status=DailyReadingStatus.BUILDING.value,
            )
            session.add(reading_list)

        with timed_stage(logger, "daily.select"):
            selected: list[ScoredCandidate] = []
            total_minutes = 0
            candidates = _eligible_candidates(
                session,
                current_settings,
                current_time,
                user_id,
                target_article_minutes,
            )
            for candidate in candidates:
                if len(selected) >= target_count:
                    break
                if (
                    total_minutes + candidate.reading_minutes
                    > target_total_minutes
                ):
                    continue
                selected.append(candidate)
                total_minutes += candidate.reading_minutes

        with timed_stage(logger, "daily.persist", selected_count=len(selected)):
            for rank, candidate in enumerate(selected, start=1):
                personal_reasons = "; ".join(candidate.personalization.reasons)
                selection_reason = candidate.base_score.reason
                if personal_reasons:
                    selection_reason += f"; personalization: {personal_reasons}"
                reading_list.items.append(
                    DailyReadingItem(
                        article=candidate.article,
                        rank=rank,
                        total_score=candidate.total_score,
                        base_score=candidate.base_score.total,
                        personalization_score=candidate.personalization.score,
                        freshness_score=candidate.base_score.freshness,
                        topic_score=candidate.base_score.topic,
                        source_score=candidate.base_score.source,
                        length_score=candidate.base_score.length,
                        reading_minutes=candidate.reading_minutes,
                        selection_reason=selection_reason,
                    )
                )

            reading_list.actual_article_count = len(selected)
            reading_list.actual_reading_minutes = total_minutes
            reading_list.status = DailyReadingStatus.COMPLETE.value
            session.commit()
        return get_daily_reading_list(session, list_date, user_id) or reading_list
