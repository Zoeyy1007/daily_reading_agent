from datetime import datetime
import logging
from time import perf_counter
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.tools.supplement_search import RetrievedDocument, SearchHit

logger = logging.getLogger("daily_reading.tavily")


def _published_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


class TavilySearchProvider:
    """Use Tavily only for ranked discovery; full-page text is fetched separately."""

    provider_name = "tavily"

    def __init__(self, settings: Settings) -> None:
        if settings.tavily_api_key is None:
            raise ValueError("TAVILY_API_KEY is required for Tavily web search")
        self.api_key = settings.tavily_api_key.get_secret_value()
        self.base_url = settings.tavily_base_url.rstrip("/")
        self.search_depth = settings.resolved_tavily_search_depth
        self.timeout_seconds = settings.http_timeout_seconds

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        started = perf_counter()
        logger.info(
            "tavily_call stage=request_start endpoint=%s max_results=%s url_count=%s",
            path,
            payload.get("max_results"),
            len(payload.get("urls", [])) if isinstance(payload.get("urls"), list) else 0,
        )
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception(
                "tavily_call stage=request_complete status=error endpoint=%s "
                "elapsed_ms=%.2f",
                path,
                (perf_counter() - started) * 1000,
            )
            raise
        if not isinstance(data, dict):
            raise ValueError("Tavily returned an invalid response")
        logger.info(
            "tavily_call stage=request_complete status=ok endpoint=%s elapsed_ms=%.2f "
            "request_id=%s result_count=%s failed_count=%s",
            path,
            (perf_counter() - started) * 1000,
            data.get("request_id"),
            len(data.get("results", [])) if isinstance(data.get("results"), list) else 0,
            len(data.get("failed_results", []))
            if isinstance(data.get("failed_results"), list)
            else 0,
        )
        return data

    def search(
        self, *, query: str, allowed_domains: set[str], max_results: int
    ) -> list[SearchHit]:
        payload: dict[str, object] = {
            "query": query,
            "topic": "news",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        if self.search_depth is not None:
            payload["search_depth"] = self.search_depth
        if allowed_domains:
            payload["include_domains"] = sorted(allowed_domains)

        data = self._post("search", payload)
        results = data.get("results")
        if not isinstance(results, list):
            return []
        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            publisher = (urlparse(url).hostname or "unknown").removeprefix("www.")
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    publisher=publisher,
                    published_at=_published_at(item.get("published_date")),
                    snippet=str(item.get("content") or "").strip() or None,
                    score=float(item.get("score") or 0.0),
                )
            )
        selected = hits[:max_results]
        logger.info(
            "tavily_call stage=search_normalized status=ok returned=%s allowed_domains=%s",
            len(selected),
            len(allowed_domains),
        )
        return selected


class TavilyExtractFetcher:
    """Last-resort extraction after the local article extraction pipeline fails."""

    def __init__(self, settings: Settings) -> None:
        self.minimum_words = settings.article_min_words
        self.provider = TavilySearchProvider(settings)

    def fetch(self, url: str) -> RetrievedDocument:
        logger.info("tavily_call stage=extract_fallback status=start")
        data = self.provider._post(
            "extract",
            {
                "urls": [url],
                "extract_depth": "basic",
                "format": "text",
                "include_images": False,
            },
        )
        results = data.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError("Tavily Extract returned no document")
        first = results[0]
        if not isinstance(first, dict):
            raise ValueError("Tavily Extract returned an invalid document")
        content = str(first.get("raw_content") or "").strip()
        if not content:
            raise ValueError("Tavily Extract returned empty content")
        if len(content.split()) < self.minimum_words:
            raise ValueError("Tavily Extract returned too little content")
        import hashlib

        document = RetrievedDocument(
            title=str(first.get("title") or url),
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        logger.info(
            "tavily_call stage=extract_fallback status=ok words=%s",
            len(content.split()),
        )
        return document
