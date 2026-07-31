from types import SimpleNamespace

from app.db.models import ArticleFeatureType, FeedbackReason
from app.schemas.feedback import FeedbackCreate
from app.services.preference_service import feedback_feature_values


def test_explicit_topic_reason_only_updates_selected_topic() -> None:
    event = SimpleNamespace(reason=FeedbackReason.TOPIC_POLITICS.value)
    article_features = [
        SimpleNamespace(
            feature_type=ArticleFeatureType.TOPIC.value,
            feature_value="technology",
            confidence=0.8,
        ),
        SimpleNamespace(
            feature_type=ArticleFeatureType.SOURCE.value,
            feature_value="12",
            confidence=1.0,
        ),
    ]

    assert feedback_feature_values(event, article_features) == [
        (ArticleFeatureType.TOPIC.value, "politics", 1.0)
    ]


def test_generic_feedback_still_updates_article_features() -> None:
    event = SimpleNamespace(reason=None)
    article_features = [
        SimpleNamespace(
            feature_type=ArticleFeatureType.TOPIC.value,
            feature_value="science",
            confidence=0.75,
        )
    ]

    assert feedback_feature_values(event, article_features) == [
        (ArticleFeatureType.TOPIC.value, "science", 0.75)
    ]


def test_feedback_schema_accepts_topic_reasons() -> None:
    payload = FeedbackCreate(event_type="dislike", reason="topic_technology")

    assert payload.reason == FeedbackReason.TOPIC_TECHNOLOGY
