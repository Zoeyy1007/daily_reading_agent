from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    ArticleFeature,
    ArticleFeatureType,
    FeedbackEvent,
    FeedbackEventType,
    FeedbackReason,
    PreferenceFeature,
)


EVENT_WEIGHTS: dict[str, float] = {
    FeedbackEventType.LIKE.value: 1.0,
    FeedbackEventType.DISLIKE.value: -1.0,
    FeedbackEventType.SKIP.value: -0.4,
    FeedbackEventType.OPEN.value: 0.1,
    FeedbackEventType.COMPLETE.value: 0.5,
    FeedbackEventType.STAR.value: 1.5,
}

TOPIC_REASON_VALUES: dict[str, str] = {
    FeedbackReason.TOPIC_TECHNOLOGY.value: "technology",
    FeedbackReason.TOPIC_ARTIFICIAL_INTELLIGENCE.value: "artificial intelligence",
    FeedbackReason.TOPIC_SCIENCE.value: "science",
    FeedbackReason.TOPIC_BUSINESS.value: "business",
    FeedbackReason.TOPIC_POLITICS.value: "politics",
    FeedbackReason.TOPIC_HEALTH.value: "health",
    FeedbackReason.TOPIC_CLIMATE.value: "climate",
    FeedbackReason.TOPIC_SPORTS.value: "sports",
    FeedbackReason.TOPIC_CULTURE.value: "culture",
    FeedbackReason.TOPIC_CRIME.value: "crime",
}


@dataclass(slots=True)
class FeatureAccumulator:
    positive_weight: float = 0.0
    negative_weight: float = 0.0
    positive_count: int = 0
    negative_count: int = 0


def _event_group(event_type: str) -> str:
    if event_type in {
        FeedbackEventType.LIKE.value,
        FeedbackEventType.DISLIKE.value,
        FeedbackEventType.SKIP.value,
    }:
        return "reaction"
    if event_type in {FeedbackEventType.STAR.value, FeedbackEventType.UNSTAR.value}:
        return "star"
    return event_type


def _current_feedback(events: list[FeedbackEvent]) -> list[FeedbackEvent]:
    latest: dict[tuple[int, str], FeedbackEvent] = {}
    for event in events:
        latest[(event.article_id, _event_group(event.event_type))] = event
    return [
        event
        for event in latest.values()
        if event.event_type != FeedbackEventType.UNSTAR.value
    ]


def feedback_feature_values(
    event: FeedbackEvent,
    article_features: list[ArticleFeature],
) -> list[tuple[str, str, float]]:
    """Return the features changed by one feedback event."""
    explicit_topic = TOPIC_REASON_VALUES.get(event.reason or "")
    if explicit_topic:
        return [(ArticleFeatureType.TOPIC.value, explicit_topic, 1.0)]
    return [
        (feature.feature_type, feature.feature_value, feature.confidence)
        for feature in article_features
    ]


def rebuild_preference_features(
    session: Session,
    user_id: int,
) -> list[PreferenceFeature]:
    events = list(
        session.scalars(
            select(FeedbackEvent)
            .where(FeedbackEvent.user_id == user_id)
            .order_by(FeedbackEvent.created_at, FeedbackEvent.id)
        )
    )
    current_events = _current_feedback(events)
    article_ids = {event.article_id for event in current_events}
    features = list(
        session.scalars(
            select(ArticleFeature).where(ArticleFeature.article_id.in_(article_ids))
        )
    ) if article_ids else []
    features_by_article: dict[int, list[ArticleFeature]] = defaultdict(list)
    for feature in features:
        features_by_article[feature.article_id].append(feature)

    accumulators: dict[tuple[str, str], FeatureAccumulator] = defaultdict(
        FeatureAccumulator
    )
    for event in current_events:
        weight = EVENT_WEIGHTS.get(event.event_type, 0.0)
        if weight == 0:
            continue
        event_features = feedback_feature_values(
            event, features_by_article[event.article_id]
        )
        for feature_type, feature_value, feature_confidence in event_features:
            adjusted = weight * feature_confidence
            accumulator = accumulators[(feature_type, feature_value)]
            if adjusted > 0:
                accumulator.positive_weight += adjusted
                accumulator.positive_count += 1
            else:
                accumulator.negative_weight += abs(adjusted)
                accumulator.negative_count += 1

    session.execute(
        delete(PreferenceFeature).where(PreferenceFeature.user_id == user_id)
    )
    session.flush()
    rebuilt: list[PreferenceFeature] = []
    for (feature_type, feature_value), values in sorted(accumulators.items()):
        total_weight = values.positive_weight + values.negative_weight
        total_count = values.positive_count + values.negative_count
        preference = PreferenceFeature(
            user_id=user_id,
            feature_type=feature_type,
            feature_value=feature_value,
            score=(values.positive_weight - values.negative_weight) / total_weight,
            confidence=min(1.0, total_count / 5),
            positive_count=values.positive_count,
            negative_count=values.negative_count,
        )
        session.add(preference)
        rebuilt.append(preference)
    session.flush()
    return rebuilt
