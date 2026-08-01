import re
from collections import Counter

from bs4 import BeautifulSoup, Tag


_NOISE_TAGS = ("nav", "footer", "aside", "form", "dialog", "script", "style", "svg", "noscript")
_NOISE_ROLES = {"navigation", "complementary", "contentinfo", "dialog", "menu"}
_NOISE_ATTRIBUTE_PARTS = (
    "navigation",
    "navbar",
    "nav-menu",
    "site-menu",
    "sidebar",
    "related-content",
    "related-stories",
    "recommendation",
    "recommended",
    "most-read",
    "most-popular",
    "top-stories",
    "promo-list",
    "share-tools",
    "social-share",
    "newsletter",
    "subscription",
    "cookie-banner",
    "consent-banner",
    "media-player",
    "video-player",
)
_EXACT_NOISE_LINES = {
    "audio",
    "business",
    "culture",
    "documentaries",
    "earth",
    "health",
    "home",
    "live",
    "news",
    "save",
    "share",
    "sign in",
    "sport",
    "sports",
    "subscribe",
    "technology",
    "travel",
    "video",
    "watch live",
}
_NOISE_HEADINGS = {
    "explore more",
    "more on this story",
    "more from this section",
    "most read",
    "related content",
    "related stories",
    "recommended stories",
    "top stories",
}
_DURATION_PATTERN = re.compile(r"^(?:\d{1,2}:)?\d{1,2}:\d{2}$")
_MARKDOWN_LINK_PATTERN = re.compile(r"^\[([^]]+)]\([^)]*\)$")


def _attribute_text(element: Tag) -> str:
    values: list[str] = []
    for attribute in ("id", "class", "data-component", "data-testid", "aria-label"):
        value = element.get(attribute)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    return " ".join(values).casefold()


def prune_page_html(html: str) -> str:
    """Remove structural page chrome before the article extractor sees it."""
    soup = BeautifulSoup(html, "lxml")
    for element in list(soup.find_all(_NOISE_TAGS)):
        element.decompose()
    for element in list(soup.find_all(True)):
        if element.parent is None:
            continue
        role = str(element.get("role") or "").casefold()
        attributes = _attribute_text(element)
        if role in _NOISE_ROLES or any(
            part in attributes for part in _NOISE_ATTRIBUTE_PARTS
        ):
            element.decompose()
    return str(soup)


def _visible_label(line: str) -> str:
    match = _MARKDOWN_LINK_PATTERN.fullmatch(line)
    return match.group(1).strip() if match else line


def clean_article_text(text: str) -> str:
    """Remove high-confidence residual navigation and embedded-media boilerplate."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    folded_counts = Counter(line.casefold() for line in lines if len(line.split()) <= 5)
    cleaned: list[str] = []
    for line in lines:
        label = _visible_label(line)
        folded = label.casefold().strip(" :")
        if folded in _EXACT_NOISE_LINES or folded in _NOISE_HEADINGS:
            continue
        if _DURATION_PATTERN.fullmatch(label):
            continue
        if folded.startswith(("watch:", "listen:", "video:")):
            continue
        if len(label.split()) <= 3 and folded_counts[line.casefold()] >= 2:
            continue
        cleaned.append(line)
    return "\n\n".join(cleaned)
