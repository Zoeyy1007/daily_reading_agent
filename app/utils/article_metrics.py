import math
from datetime import datetime


def calculate_reading_minutes(word_count: int, words_per_minute: int = 225) -> int:
    if word_count < 0:
        raise ValueError("word_count cannot be negative")
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")
    return max(1, math.ceil(word_count / words_per_minute))


def hours_since(published_at: datetime, now: datetime) -> float:
    if published_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("published_at and now must be timezone-aware")
    return max(0.0, (now - published_at).total_seconds() / 3600)


def combined_article_text(article: object) -> str:
    values = (
        getattr(article, "title", None),
        getattr(article, "rss_summary", None),
        getattr(article, "content_text", None),
    )
    return "\n".join(str(value) for value in values if value).casefold()
