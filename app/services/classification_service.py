import re

import py3langid as langid

from app.utils.article_metrics import combined_article_text


CONTENT_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("opinion", ("opinion", "editorial", "commentary", "op-ed", "opinion piece")),
    ("analysis", ("analysis", "explainer", "what it means", "in depth")),
    ("tutorial", ("tutorial", "how to", "how-to", "step-by-step", "guide")),
)


def detect_language(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "unknown"
    language, _confidence = langid.classify(normalized[:20_000])
    return language.casefold()


def classify_content_type(article: object) -> str:
    title = str(getattr(article, "title", "") or "").casefold()
    url = str(getattr(article, "canonical_url", "") or "").casefold()
    searchable = f"{title} {url}"
    for content_type, patterns in CONTENT_TYPE_PATTERNS:
        if any(re.search(rf"\b{re.escape(pattern)}\b", searchable) for pattern in patterns):
            return content_type
    return "news"


def enrich_article(article: object) -> None:
    if not getattr(article, "language", None):
        article.language = detect_language(combined_article_text(article))
    if not getattr(article, "content_type", None):
        article.content_type = classify_content_type(article)
