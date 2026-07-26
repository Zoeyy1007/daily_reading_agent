from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import ArticleFeature, FeedbackEvent, FeedbackEventType, PreferenceFeature


EVENT_WEIGHTS: dict[str, float] = {
    FeedbackEventType.LIKE.value: 1.0,
    FeedbackEventType.DISLIKE.value: -1.0,
    FeedbackEventType.SKIP.value: -0.4,
    FeedbackEventType.OPEN.value: 0.1,
    FeedbackEventType.COMPLETE.value: 0.5,
    FeedbackEventType.STAR.value: 1.5,
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
        for feature in features_by_article[event.article_id]:
            adjusted = weight * feature.confidence
            accumulator = accumulators[(feature.feature_type, feature.feature_value)]
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
