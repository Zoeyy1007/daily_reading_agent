from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.utils.article_metrics import combined_article_text, hours_since


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total: float
    freshness: float
    topic: float
    source: float
    length: float
    matched_topics: tuple[str, ...]
    reason: str


def _freshness_score(article: object, settings: Settings, now: datetime) -> float:
    publication_time = getattr(article, "published_at", None) or getattr(
        article, "discovered_at"
    )
    age = hours_since(publication_time, now)
    return max(0.0, 40.0 * (1.0 - age / settings.max_article_age_hours))


def _topic_score(article: object, settings: Settings) -> tuple[float, tuple[str, ...]]:
    topics = settings.preferred_topic_set
    if not topics:
        return 15.0, ()
    searchable = combined_article_text(article)
    matches = tuple(sorted(topic for topic in topics if topic in searchable))
    return 30.0 * len(matches) / len(topics), matches


def _source_score(article: object, settings: Settings) -> float:
    if not settings.preferred_source_id_set:
        return 10.0
    return 20.0 if getattr(article, "source_id", None) in settings.preferred_source_id_set else 5.0


def _length_score(article: object, settings: Settings) -> float:
    word_count = int(getattr(article, "word_count"))
    ideal = (settings.min_article_words + settings.max_article_words) / 2
    half_range = max(1.0, (settings.max_article_words - settings.min_article_words) / 2)
    return max(0.0, 10.0 * (1.0 - abs(word_count - ideal) / half_range))


def score_article(article: object, settings: Settings, *, now: datetime) -> ScoreResult:
    freshness = _freshness_score(article, settings, now)
    topic, matched_topics = _topic_score(article, settings)
    source = _source_score(article, settings)
    length = _length_score(article, settings)
    total = freshness + topic + source + length

    reason_parts = [f"freshness {freshness:.1f}/40", f"length fit {length:.1f}/10"]
    if matched_topics:
        reason_parts.append(f"matched topics: {', '.join(matched_topics)}")
    elif settings.preferred_topic_set:
        reason_parts.append("no preferred-topic match")
    if getattr(article, "source_id", None) in settings.preferred_source_id_set:
        reason_parts.append("preferred source")

    return ScoreResult(
        total=round(total, 2),
        freshness=round(freshness, 2),
        topic=round(topic, 2),
        source=round(source, 2),
        length=round(length, 2),
        matched_topics=matched_topics,
        reason="; ".join(reason_parts),
    )
