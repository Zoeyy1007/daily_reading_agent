from types import SimpleNamespace

from app.config import Settings
from app.db.models import FeedbackEventType
from app.services.article_feature_service import extract_article_features
from app.services.personalization_service import (
    preference_index,
    score_personalization,
)
from app.services.preference_service import _current_feedback


def test_article_features_include_source_type_and_topics() -> None:
    article = SimpleNamespace(
        source_id=3,
        source=SimpleNamespace(publisher_id=7, category="Technology"),
        content_type="analysis",
        title="AI technology changes the chip market",
        rss_summary="Researchers discuss artificial intelligence.",
        content_text="A software and machine learning report.",
    )
    features = {
        (feature.feature_type, feature.feature_value)
        for feature in extract_article_features(article)
    }
    assert ("publisher", "7") in features
    assert ("category", "technology") in features
    assert ("content_type", "analysis") in features
    assert ("topic", "technology") in features
    assert ("topic", "artificial intelligence") in features


def test_crime_topic_accepts_related_keywords() -> None:
    article = SimpleNamespace(
        source=SimpleNamespace(publisher_id=4, category="News"),
        content_type="news",
        title="Police arrest suspect in robbery investigation",
        rss_summary="A prosecutor announced criminal charges.",
        content_text="The crime investigation is continuing.",
    )
    features = extract_article_features(article)
    assert any(
        feature.feature_type == "topic" and feature.feature_value == "crime"
        for feature in features
    )


def test_current_feedback_uses_latest_reaction_and_star_state() -> None:
    events = [
        SimpleNamespace(id=1, article_id=10, event_type=FeedbackEventType.LIKE.value),
        SimpleNamespace(id=2, article_id=10, event_type=FeedbackEventType.DISLIKE.value),
        SimpleNamespace(id=3, article_id=10, event_type=FeedbackEventType.STAR.value),
        SimpleNamespace(id=4, article_id=10, event_type=FeedbackEventType.UNSTAR.value),
    ]
    current = _current_feedback(events)  # type: ignore[arg-type]
    assert [event.event_type for event in current] == [FeedbackEventType.DISLIKE.value]


def test_personalization_uses_confidence_and_feature_confidence() -> None:
    settings = Settings(_env_file=None, personalization_weight=30)
    preference = SimpleNamespace(
        feature_type="topic",
        feature_value="technology",
        score=1.0,
        confidence=0.5,
    )
    feature = SimpleNamespace(
        feature_type="topic",
        feature_value="technology",
        confidence=0.8,
    )
    result = score_personalization(
        [feature],  # type: ignore[list-item]
        preference_index([preference]),  # type: ignore[list-item]
        settings,
    )
    assert result.score == 12.0
    assert "topic 'technology' preferred" in result.reasons
