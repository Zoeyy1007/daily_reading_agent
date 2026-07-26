from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Article, ArticleFeature, ArticleFeatureType
from app.utils.article_metrics import combined_article_text


TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "technology": ("technology", "software", "computer", "cybersecurity", "chip"),
    "artificial intelligence": ("artificial intelligence", "machine learning", " ai "),
    "science": ("science", "researcher", "study", "space", "physics", "biology"),
    "business": ("business", "company", "market", "economy", "finance", "stock"),
    "politics": ("politics", "election", "government", "congress", "president"),
    "health": ("health", "medical", "medicine", "hospital", "disease"),
    "climate": ("climate", "global warming", "emissions", "renewable energy"),
    "sports": ("sports", "football", "basketball", "baseball", "soccer", "tennis"),
    "culture": ("culture", "film", "music", "book", "television", "art"),
    "crime": ("crime", "criminal", "homicide", "robbery", "prosecutor", "police"),
}


@dataclass(frozen=True, slots=True)
class ExtractedFeature:
    feature_type: str
    feature_value: str
    confidence: float


def extract_article_features(article: object) -> tuple[ExtractedFeature, ...]:
    source = getattr(article, "source", None)
    publisher_id = getattr(source, "publisher_id", None)
    category = getattr(source, "category", None)
    features = [
        ExtractedFeature(
            ArticleFeatureType.CONTENT_TYPE.value,
            str(getattr(article, "content_type", None) or "unknown").casefold(),
            1.0,
        ),
    ]
    if publisher_id is not None:
        features.append(
            ExtractedFeature(
                ArticleFeatureType.PUBLISHER.value,
                str(publisher_id),
                1.0,
            )
        )
    if category:
        features.append(
            ExtractedFeature(
                ArticleFeatureType.CATEGORY.value,
                str(category).casefold(),
                1.0,
            )
        )
    searchable = f" {combined_article_text(article)} "
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword.casefold() in searchable for keyword in keywords):
            features.append(ExtractedFeature(ArticleFeatureType.TOPIC.value, topic, 0.8))
    return tuple(features)


def ensure_article_features(
    session: Session,
    articles: list[Article],
) -> dict[int, list[ArticleFeature]]:
    if not articles:
        return {}
    article_ids = [article.id for article in articles]
    existing = session.scalars(
        select(ArticleFeature).where(ArticleFeature.article_id.in_(article_ids))
    ).all()
    by_article: dict[int, list[ArticleFeature]] = {
        article_id: [] for article_id in article_ids
    }
    for feature in existing:
        by_article[feature.article_id].append(feature)

    for article in articles:
        if by_article[article.id]:
            continue
        for extracted in extract_article_features(article):
            feature = ArticleFeature(
                article_id=article.id,
                feature_type=extracted.feature_type,
                feature_value=extracted.feature_value,
                confidence=extracted.confidence,
            )
            session.add(feature)
            by_article[article.id].append(feature)
    session.flush()
    return by_article
