from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.db.models import ArticleStatus
from app.utils.article_metrics import hours_since


@dataclass(frozen=True, slots=True)
class FilterResult:
    accepted: bool
    reasons: tuple[str, ...]


def filter_article(
    article: object,
    settings: Settings,
    *,
    now: datetime,
) -> FilterResult:
    reasons: list[str] = []
    if getattr(article, "status", None) != ArticleStatus.EXTRACTED.value:
        reasons.append("not_extracted")
    if not getattr(article, "content_text", None):
        reasons.append("missing_content")

    word_count = getattr(article, "word_count", None)
    if word_count is None:
        reasons.append("missing_word_count")
    elif word_count < settings.min_article_words:
        reasons.append("too_short")
    elif word_count > settings.max_article_words:
        reasons.append("too_long")

    publication_time = getattr(article, "published_at", None) or getattr(
        article, "discovered_at", None
    )
    if publication_time is None:
        reasons.append("missing_publication_date")
    elif hours_since(publication_time, now) > settings.max_article_age_hours:
        reasons.append("too_old")

    language = str(getattr(article, "language", "") or "").casefold()
    if language not in settings.allowed_language_set:
        reasons.append("language_not_allowed")

    content_type = str(getattr(article, "content_type", "") or "").casefold()
    if content_type not in settings.allowed_content_type_set:
        reasons.append("content_type_not_allowed")

    if getattr(article, "source_id", None) in settings.blocked_source_id_set:
        reasons.append("blocked_source")

    return FilterResult(accepted=not reasons, reasons=tuple(reasons))
