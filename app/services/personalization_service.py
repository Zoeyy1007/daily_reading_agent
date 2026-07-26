from dataclasses import dataclass

from app.config import Settings
from app.db.models import ArticleFeature, PreferenceFeature


@dataclass(frozen=True, slots=True)
class PersonalizationResult:
    score: float
    reasons: tuple[str, ...]


def preference_index(
    preferences: list[PreferenceFeature],
) -> dict[tuple[str, str], PreferenceFeature]:
    return {
        (preference.feature_type, preference.feature_value): preference
        for preference in preferences
    }


def score_personalization(
    features: list[ArticleFeature],
    preferences: dict[tuple[str, str], PreferenceFeature],
    settings: Settings,
) -> PersonalizationResult:
    contributions: list[tuple[float, ArticleFeature]] = []
    for feature in features:
        preference = preferences.get((feature.feature_type, feature.feature_value))
        if preference is None:
            continue
        contribution = preference.score * preference.confidence * feature.confidence
        contributions.append((contribution, feature))

    if not contributions:
        return PersonalizationResult(0.0, ())
    normalized = sum(value for value, _feature in contributions) / len(contributions)
    score = round(normalized * settings.personalization_weight, 2)
    strongest = sorted(contributions, key=lambda item: abs(item[0]), reverse=True)[:3]
    reasons = tuple(
        f"{feature.feature_type} '{feature.feature_value}' "
        f"{'preferred' if contribution > 0 else 'avoided'}"
        for contribution, feature in strongest
        if contribution != 0
    )
    return PersonalizationResult(score, reasons)
