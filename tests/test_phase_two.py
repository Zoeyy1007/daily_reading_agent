from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.classification_service import (
    classify_content_type,
    detect_language,
)
from app.services.filter_service import filter_article
from app.services.scoring_service import score_article
from app.utils.article_metrics import calculate_reading_minutes


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "min_article_words": 200,
        "max_article_words": 2000,
        "max_article_age_hours": 48,
        "allowed_languages": "en",
        "allowed_content_types": "news,analysis",
        "preferred_topics": "technology,science",
        "preferred_source_ids": "1",
        "blocked_source_ids": "",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def make_article(now: datetime, **overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "source_id": 1,
        "status": "extracted",
        "title": "New technology advances in science",
        "rss_summary": "Researchers announced a new result.",
        "content_text": "technology science research " * 300,
        "canonical_url": "https://example.com/story",
        "word_count": 900,
        "language": "en",
        "content_type": "news",
        "published_at": now - timedelta(hours=6),
        "discovered_at": now - timedelta(hours=5),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_reading_minutes_rounds_up() -> None:
    assert calculate_reading_minutes(451, 225) == 3
    with pytest.raises(ValueError):
        calculate_reading_minutes(100, 0)


def test_language_and_content_type_classification() -> None:
    assert detect_language("This is a clearly written English news article. " * 20) == "en"
    article = SimpleNamespace(
        title="Analysis: what the election result means",
        canonical_url="https://example.com/politics/story",
    )
    assert classify_content_type(article) == "analysis"


def test_filter_returns_specific_rejection_reasons() -> None:
    now = datetime.now(UTC)
    settings = make_settings(blocked_source_ids="5")
    article = make_article(
        now,
        source_id=5,
        language="fr",
        word_count=100,
        published_at=now - timedelta(hours=60),
    )
    result = filter_article(article, settings, now=now)
    assert not result.accepted
    assert set(result.reasons) == {
        "too_short",
        "too_old",
        "language_not_allowed",
        "blocked_source",
    }


def test_scoring_rewards_fresh_topic_and_preferred_source() -> None:
    now = datetime.now(UTC)
    settings = make_settings()
    preferred = score_article(make_article(now), settings, now=now)
    unrelated = score_article(
        make_article(
            now,
            source_id=2,
            title="Local arts event",
            rss_summary="A gallery opened.",
            content_text="painting gallery exhibition " * 300,
            published_at=now - timedelta(hours=30),
        ),
        settings,
        now=now,
    )
    assert preferred.total > unrelated.total
    assert preferred.matched_topics == ("science", "technology")
    assert preferred.source == 20.0
