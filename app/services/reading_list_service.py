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
)
from app.services.classification_service import enrich_article
from app.services.filter_service import filter_article
from app.services.scoring_service import ScoreResult, score_article
from app.utils.article_metrics import calculate_reading_minutes


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    article: Article
    score: ScoreResult
    reading_minutes: int


def local_today(settings: Settings | None = None) -> date:
    current_settings = settings or get_settings()
    return datetime.now(ZoneInfo(current_settings.scheduler_timezone)).date()


def get_daily_reading_list(
    session: Session, list_date: date
) -> DailyReadingList | None:
    return session.scalar(
        select(DailyReadingList)
        .where(DailyReadingList.list_date == list_date)
        .options(
            selectinload(DailyReadingList.items).selectinload(DailyReadingItem.article)
        )
    )


def _eligible_candidates(
    session: Session,
    settings: Settings,
    now: datetime,
) -> list[ScoredCandidate]:
    articles = session.scalars(
        select(Article).where(
            Article.status == ArticleStatus.EXTRACTED.value,
            Article.content_text.is_not(None),
        )
    ).all()
    candidates: list[ScoredCandidate] = []
    for article in articles:
        enrich_article(article)
        result = filter_article(article, settings, now=now)
        if not result.accepted:
            continue
        candidates.append(
            ScoredCandidate(
                article=article,
                score=score_article(article, settings, now=now),
                reading_minutes=calculate_reading_minutes(
                    article.word_count or 0, settings.reading_words_per_minute
                ),
            )
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.score.total,
            candidate.article.published_at or candidate.article.discovered_at,
        ),
        reverse=True,
    )
    return candidates


def generate_daily_reading_list(
    session: Session,
    list_date: date,
    *,
    regenerate: bool = False,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> DailyReadingList:
    current_settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    existing = get_daily_reading_list(session, list_date)
    if existing and not regenerate:
        return existing

    if existing:
        reading_list = existing
        reading_list.items.clear()
        # Delete old ranks/articles before inserting replacements with the same
        # unique keys during a regeneration.
        session.flush()
        reading_list.target_article_count = current_settings.daily_article_target
        reading_list.target_reading_minutes = current_settings.daily_reading_minutes
        reading_list.status = DailyReadingStatus.BUILDING.value
    else:
        reading_list = DailyReadingList(
            list_date=list_date,
            target_article_count=current_settings.daily_article_target,
            target_reading_minutes=current_settings.daily_reading_minutes,
            actual_article_count=0,
            actual_reading_minutes=0,
            status=DailyReadingStatus.BUILDING.value,
        )
        session.add(reading_list)

    selected: list[ScoredCandidate] = []
    total_minutes = 0
    for candidate in _eligible_candidates(session, current_settings, current_time):
        if len(selected) >= current_settings.daily_article_target:
            break
        if total_minutes + candidate.reading_minutes > current_settings.daily_reading_minutes:
            continue
        selected.append(candidate)
        total_minutes += candidate.reading_minutes

    for rank, candidate in enumerate(selected, start=1):
        reading_list.items.append(
            DailyReadingItem(
                article=candidate.article,
                rank=rank,
                total_score=candidate.score.total,
                freshness_score=candidate.score.freshness,
                topic_score=candidate.score.topic,
                source_score=candidate.score.source,
                length_score=candidate.score.length,
                reading_minutes=candidate.reading_minutes,
                selection_reason=candidate.score.reason,
            )
        )

    reading_list.actual_article_count = len(selected)
    reading_list.actual_reading_minutes = total_minutes
    reading_list.status = DailyReadingStatus.COMPLETE.value
    session.commit()
    return get_daily_reading_list(session, list_date) or reading_list
