import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import trafilatura

from app.services.article_cleaner import clean_article_text, prune_page_html


class ExtractionFailedError(RuntimeError):
    pass


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
    ) -> None:
        self.client = client
        self.minimum_words = minimum_words
        self.jina_api_key = jina_api_key
        self.use_jina_fallback = use_jina_fallback

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

    def extract(self, url: str) -> ExtractedArticle:
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
                headers = {"Accept": "text/plain", "X-Return-Format": "text"}
                if self.jina_api_key:
                    headers["Authorization"] = f"Bearer {self.jina_api_key}"
                response = self.client.get(f"https://r.jina.ai/{url}", headers=headers)
                response.raise_for_status()
                result = self._result(response.text, extractor="jina")
                if result:
                    return result
                errors.append("jina returned too little content")
            except Exception as exc:
                errors.append(f"jina: {exc}")

        raise ExtractionFailedError("; ".join(errors))
