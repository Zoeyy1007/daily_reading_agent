import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Article,
    ArticleChunk,
    Publisher,
    Source,
    StoryCluster,
    StoryClusterMember,
)
from app.services.phase_five_service import (
    _bm25_scores,
    _cosine,
    _normalize_scores,
    split_article_content,
)
from app.services.article_extractor import ArticleExtractor, ExtractionFailedError

logger = logging.getLogger("daily_reading.supplement_tools")


@dataclass(frozen=True, slots=True)
class LocalSearchMatch:
    article_id: int
    chunk_id: int
    title: str
    publisher: str
    url: str
    published_at: datetime | None
    excerpt: str
    score: float
    relationship: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    publisher: str
    published_at: datetime | None = None
    jurisdiction: str | None = None
    agency: str | None = None
    document_type: str | None = None
    document_identifier: str | None = None
    effective_date: date | None = None
    snippet: str | None = None
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class CollectedChunk:
    excerpt: str
    content_hash: str


class ExternalSearchProvider(Protocol):
    provider_name: str

    def search(
        self,
        *,
        query: str,
        allowed_domains: set[str],
        max_results: int,
        start_date: date | None,
        end_date: date | None,
    ) -> list[SearchHit]: ...


class DocumentFetcher(Protocol):
    def fetch(self, url: str) -> RetrievedDocument: ...


def normalized_hostname(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def domain_allowed(url: str, allowed_domains: set[str]) -> bool:
    hostname = normalized_hostname(url)
    return bool(hostname) and any(
        hostname == domain.casefold().removeprefix("www.")
        or hostname.endswith("." + domain.casefold().removeprefix("www."))
        for domain in allowed_domains
    )


def collect_chunk(*, text: str, url: str, max_words: int) -> CollectedChunk:
    """Normalize one bounded excerpt before it enters the evidence workspace."""
    excerpt = " ".join(text.split()[:max_words])
    return CollectedChunk(
        excerpt=excerpt,
        content_hash=hashlib.sha256(f"{url}\n{excerpt}".encode("utf-8")).hexdigest(),
    )


def local_cluster_search(
    session: Session,
    *,
    selected_article_id: int,
    query: str,
    settings: Settings,
    limit: int,
    allowed_relationships: set[str],
    start_date: date | None,
    end_date: date | None,
) -> tuple[int | None, list[LocalSearchMatch]]:
    if not allowed_relationships:
        return None, []
    cluster = session.scalar(
        select(StoryCluster)
        .join(StoryClusterMember, StoryClusterMember.cluster_id == StoryCluster.id)
        .where(StoryClusterMember.article_id == selected_article_id)
    )
    if cluster is None:
        return None, []

    query_statement = (
        select(ArticleChunk, Article, Publisher, StoryClusterMember.relationship)
        .join(Article, Article.id == ArticleChunk.article_id)
        .join(Source, Source.id == Article.source_id)
        .join(Publisher, Publisher.id == Source.publisher_id)
        .join(StoryClusterMember, StoryClusterMember.article_id == Article.id)
        .where(
            StoryClusterMember.cluster_id == cluster.id,
            Article.id != selected_article_id,
            StoryClusterMember.relationship.in_(allowed_relationships),
        )
        .order_by(
            StoryClusterMember.relationship,
            Article.id,
            ArticleChunk.chunk_index,
        )
    )
    if start_date is not None:
        query_statement = query_statement.where(
            Article.published_at >= datetime.combine(start_date, time.min, tzinfo=UTC)
        )
    if end_date is not None:
        query_statement = query_statement.where(
            Article.published_at
            < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        )
    rows = session.execute(query_statement).all()
    if not rows:
        return cluster.id, []

    chunks = [row[0] for row in rows]
    bm25 = _normalize_scores(_bm25_scores(query, [chunk.chunk_text for chunk in chunks]))
    vector = [
        max(
            0.0,
            min(
                1.0,
                (_cosine(list(chunk.embedding), list(cluster.centroid_embedding)) + 1.0)
                / 2.0,
            ),
        )
        if chunk.embedding is not None
        else 0.0
        for chunk in chunks
    ]
    total_weight = settings.evidence_bm25_weight + settings.evidence_vector_weight
    bm25_weight = settings.evidence_bm25_weight / total_weight if total_weight else 0.5
    vector_weight = settings.evidence_vector_weight / total_weight if total_weight else 0.5
    ranked = [
        LocalSearchMatch(
            article_id=article.id,
            chunk_id=chunk.id,
            title=article.title,
            publisher=publisher.name,
            url=article.canonical_url,
            published_at=article.published_at,
            excerpt=chunk.chunk_text,
            score=bm25_weight * lexical + vector_weight * semantic,
            relationship=relationship,
        )
        for (chunk, article, publisher, relationship), lexical, semantic in zip(
            rows, bm25, vector, strict=True
        )
    ]
    ranked.sort(
        key=lambda item: (
            item.relationship == "coverage",
            item.score,
            -item.chunk_id,
        ),
        reverse=True,
    )

    selected: list[LocalSearchMatch] = []
    selected_chunks: set[int] = set()
    for article_id in dict.fromkeys(item.article_id for item in ranked):
        best = next(item for item in ranked if item.article_id == article_id)
        selected.append(best)
        selected_chunks.add(best.chunk_id)
        if len(selected) >= limit:
            return cluster.id, selected
    for item in ranked:
        if item.chunk_id in selected_chunks:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return cluster.id, selected


class HttpDocumentFetcher:
    def __init__(
        self,
        settings: Settings,
        *,
        fallback: DocumentFetcher | None = None,
    ) -> None:
        self.settings = settings
        self.fallback = fallback

    def fetch(self, url: str) -> RetrievedDocument:
        headers = {"User-Agent": self.settings.user_agent}
        try:
            if urlparse(url).path.casefold().endswith(".pdf"):
                with httpx.Client(
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(response.content))
                content = "\n\n".join(page.extract_text() or "" for page in reader.pages)
                content = "\n\n".join(
                    line.strip() for line in content.splitlines() if line.strip()
                )
                if len(content.split()) < self.settings.article_min_words:
                    raise ExtractionFailedError("PDF returned too little content")
                return RetrievedDocument(
                    title=urlparse(str(response.url)).path.rsplit("/", 1)[-1],
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            with httpx.Client(
                timeout=self.settings.http_timeout_seconds,
                follow_redirects=True,
                headers=headers,
            ) as client:
                extracted = ArticleExtractor(
                    client,
                    minimum_words=self.settings.article_min_words,
                    use_jina_fallback=False,
                ).extract(url)
            logger.info(
                "supplement_extract status=ok extractor=%s words=%s",
                extracted.extractor,
                extracted.word_count,
            )
            return RetrievedDocument(
                title=extracted.title or url,
                content=extracted.content,
                content_hash=extracted.content_hash,
            )
        except Exception as primary_error:
            if self.fallback is None:
                raise ValueError(str(primary_error)) from primary_error
            logger.warning(
                "supplement_extract status=fallback primary_error=%s",
                primary_error,
            )
            try:
                return self.fallback.fetch(url)
            except Exception as fallback_error:
                raise ValueError(
                    f"Local extraction failed: {primary_error}; "
                    f"fallback extraction failed: {fallback_error}"
                ) from fallback_error


def best_document_excerpt(content: str, query: str, *, target_words: int = 350) -> str:
    pieces = split_article_content(
        content, target_words=target_words, overlap_words=min(60, target_words // 4)
    )
    if not pieces:
        return ""
    texts = [piece[0] for piece in pieces]
    scores = _bm25_scores(query, texts)
    best_index = max(range(len(texts)), key=lambda index: (scores[index], -index))
    return texts[best_index]
