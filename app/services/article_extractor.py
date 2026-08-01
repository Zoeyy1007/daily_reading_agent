import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import trafilatura

from app.services.article_cleaner import clean_article_text, prune_page_html


JINA_REMOVE_SELECTOR = ", ".join(
    (
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "dialog",
        '[role="navigation"]',
        '[role="contentinfo"]',
        '[role="complementary"]',
        '[role="menu"]',
        '[class*="sidebar"]',
        '[class*="recommend"]',
        '[class*="related"]',
        '[class*="most-read"]',
        '[class*="top-stories"]',
        '[class*="promo-list"]',
        '[data-testid*="sidebar"]',
        '[data-testid*="recommend"]',
        '[data-testid*="related"]',
        '[data-testid*="vertical-video"]',
        '[data-testid*="video-grid"]',
        '[class*="advertisement"]',
        '[class*="ad-slot"]',
        '[data-component*="advertisement"]',
        '[data-component*="ad-slot"]',
        '[data-testid*="ad-unit"]',
    )
)
_MEDIA_PATH_SEGMENTS = {
    "audio",
    "live",
    "livestream",
    "podcast",
    "podcasts",
    "video",
    "videos",
}
_MEDIA_TITLE_PATTERN = re.compile(
    r"^(?:watch|listen)(?:\s+live)?\s*:|\blive\s+stream\b",
    flags=re.IGNORECASE,
)


class ExtractionFailedError(RuntimeError):
    pass


def is_probable_media_page(url: str, title: str | None = None) -> bool:
    """Reject clear video, audio, and live-stream pages before downloading them."""
    path_segments = {
        segment.casefold()
        for segment in urlsplit(url).path.split("/")
        if segment
    }
    if path_segments & _MEDIA_PATH_SEGMENTS:
        return True
    return bool(title and _MEDIA_TITLE_PATTERN.search(title.strip()))


@dataclass(slots=True)
class ExtractedArticle:
    content: str
    author: str | None
    title: str | None
    word_count: int
    content_hash: str
    extractor: str
    fetched_at: datetime


class ArticleExtractor:
    def __init__(
        self,
        client: httpx.Client,
        *,
        minimum_words: int,
        jina_api_key: str | None = None,
        use_jina_fallback: bool = True,
        jina_no_cache: bool = False,
    ) -> None:
        self.client = client
        self.minimum_words = minimum_words
        self.jina_api_key = jina_api_key
        self.use_jina_fallback = use_jina_fallback
        self.jina_no_cache = jina_no_cache

    def _jina_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "text/plain",
            "X-Respond-With": "content",
            "X-Remove-Selector": JINA_REMOVE_SELECTOR,
            "X-Retain-Images": "none",
            "X-Retain-Media": "none",
            "X-Retain-Links": "text",
        }
        if self.jina_no_cache:
            headers["X-No-Cache"] = "true"
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"
        return headers

    @staticmethod
    def _normalize(text: str) -> str:
        return clean_article_text(text)

    def _result(
        self,
        text: str | None,
        *,
        extractor: str,
        author: str | None = None,
        title: str | None = None,
    ) -> ExtractedArticle | None:
        if not text:
            return None
        content = self._normalize(text)
        word_count = len(content.split())
        if word_count < self.minimum_words:
            return None
        return ExtractedArticle(
            content=content,
            author=author,
            title=title,
            word_count=word_count,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            extractor=extractor,
            fetched_at=datetime.now(UTC),
        )

    def extract(self, url: str, *, title: str | None = None) -> ExtractedArticle:
        if is_probable_media_page(url, title):
            raise ExtractionFailedError("unsupported video, audio, or live-stream page")
        errors: list[str] = []
        html_text: str | None = None

        try:
            response = self.client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type and "xhtml" not in content_type:
                raise ValueError(f"unsupported content type: {content_type or 'unknown'}")
            html_text = prune_page_html(response.text)
            raw = trafilatura.extract(
                html_text,
                url=str(response.url),
                output_format="json",
                with_metadata=True,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            data = json.loads(raw) if raw else {}
            result = self._result(
                data.get("text"),
                extractor="trafilatura",
                author=data.get("author"),
                title=data.get("title"),
            )
            if result:
                return result
            errors.append("trafilatura returned too little content")
        except Exception as exc:
            errors.append(f"trafilatura: {exc}")

        if html_text:
            try:
                import newspaper

                article = newspaper.Article(url)
                article.download(input_html=html_text)
                article.parse()
                result = self._result(
                    article.text,
                    extractor="newspaper4k",
                    author=", ".join(article.authors) or None,
                    title=article.title or None,
                )
                if result:
                    return result
                errors.append("newspaper4k returned too little content")
            except Exception as exc:
                errors.append(f"newspaper4k: {exc}")

        if self.use_jina_fallback:
            try:
                response = self.client.get(
                    f"https://r.jina.ai/{url}", headers=self._jina_headers()
                )
                response.raise_for_status()
                result = self._result(response.text, extractor="jina")
                if result:
                    return result
                errors.append("jina returned too little content")
            except Exception as exc:
                errors.append(f"jina: {exc}")

        raise ExtractionFailedError("; ".join(errors))
