import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Article, ArticleStatus, Publisher, Source
from app.db.session import SessionLocal
from app.services.article_extractor import ArticleExtractor, ExtractionFailedError
from app.sources.rss import RSSItem, fetch_rss
from app.utils.concurrency import bounded_to_thread_map
from app.utils.timing import timed_stage

logger = logging.getLogger("daily_reading.ingestion")

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


@dataclass(slots=True)
class IngestionStats:
    source_id: int
    discovered: int = 0
    extracted: int = 0
    failed: int = 0
    duplicates: int = 0
    not_modified: bool = False
    error: str | None = None
    article_ids: list[int] = field(default_factory=list)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((scheme, hostname, parts.path or "/", urlencode(sorted(query)), ""))


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _find_duplicate(session: Session, source_id: int, item: RSSItem, url_hash: str) -> Article | None:
    conditions = [Article.canonical_url_hash == url_hash]
    if item.guid:
        conditions.append(
            (Article.source_id == source_id) & (Article.rss_guid == item.guid)
        )
    return session.scalar(select(Article).where(or_(*conditions)).limit(1))


def discover_source(session: Session, source_id: int) -> IngestionStats:
    settings = get_settings()
    source = session.get(Source, source_id)
    if source is None:
        raise LookupError(f"Source {source_id} does not exist")

    stats = IngestionStats(source_id=source_id)
    timeout = httpx.Timeout(settings.http_timeout_seconds)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        with timed_stage(logger, "ingestion.fetch_rss", source_id=source_id):
            feed = fetch_rss(
                source.feed_url,
                client=client,
                etag=source.etag,
                last_modified=source.last_modified,
            )
        source.last_polled_at = datetime.now(UTC)
        if feed.etag:
            source.etag = feed.etag
        if feed.last_modified:
            source.last_modified = feed.last_modified
        if feed.not_modified:
            stats.not_modified = True
            session.commit()
            return stats

        for item in feed.items:
            canonical_url = canonicalize_url(item.url)
            url_hash = _url_hash(canonical_url)
            if _find_duplicate(session, source_id, item, url_hash):
                stats.duplicates += 1
                continue

            article = Article(
                source_id=source_id,
                rss_guid=item.guid,
                canonical_url=canonical_url,
                canonical_url_hash=url_hash,
                original_url=item.url,
                title=item.title,
                rss_summary=item.summary,
                author=item.author,
                published_at=item.published_at,
                status=ArticleStatus.DISCOVERED.value,
            )
            session.add(article)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                stats.duplicates += 1
                continue
            stats.discovered += 1
            stats.article_ids.append(article.id)

        source.last_success_at = datetime.now(UTC)
        session.commit()
    return stats


def extract_articles(session: Session, article_ids: list[int]) -> tuple[int, int]:
    """Extract discovered articles and return ``(extracted, failed)`` counts."""
    if not article_ids:
        return 0, 0
    settings = get_settings()
    extracted_count = 0
    failed_count = 0
    timeout = httpx.Timeout(settings.http_timeout_seconds)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        extractor = ArticleExtractor(
            client,
            minimum_words=settings.article_min_words,
            jina_api_key=settings.jina_api_key,
        )
        articles = list(
            session.scalars(
                select(Article)
                .where(
                    Article.id.in_(article_ids),
                    Article.status.in_(
                        [
                            ArticleStatus.DISCOVERED.value,
                            ArticleStatus.EXTRACTING.value,
                        ]
                    ),
                )
                .order_by(Article.id)
            )
        )
        for article in articles:
            article.status = ArticleStatus.EXTRACTING.value
            session.commit()
            try:
                with timed_stage(
                    logger,
                    "ingestion.extract_article",
                    source_id=article.source_id,
                    article_id=article.id,
                ):
                    extracted = extractor.extract(article.canonical_url)
                article.content_text = extracted.content
                article.author = extracted.author or article.author
                article.title = extracted.title or article.title
                article.word_count = extracted.word_count
                article.content_hash = extracted.content_hash
                article.extractor_used = extracted.extractor
                article.fetched_at = extracted.fetched_at
                article.status = ArticleStatus.EXTRACTED.value
                article.extraction_error = None
                extracted_count += 1
            except ExtractionFailedError as exc:
                article.status = ArticleStatus.FAILED.value
                article.fetched_at = datetime.now(UTC)
                article.extraction_error = str(exc)[:4000]
                failed_count += 1
            session.commit()
    return extracted_count, failed_count


def deduplicate_article_content(
    session: Session, article_ids: list[int]
) -> tuple[list[int], int]:
    """Mark same-content articles as duplicates, retaining the oldest row."""
    kept: list[int] = []
    duplicate_count = 0
    articles = list(
        session.scalars(
            select(Article)
            .where(
                Article.id.in_(article_ids),
                Article.status == ArticleStatus.EXTRACTED.value,
                Article.content_hash.is_not(None),
            )
            .order_by(Article.id)
        )
    )
    for article in articles:
        original_id = session.scalar(
            select(Article.id)
            .where(
                Article.content_hash == article.content_hash,
                Article.status == ArticleStatus.EXTRACTED.value,
                Article.id < article.id,
            )
            .order_by(Article.id)
            .limit(1)
        )
        if original_id is None:
            kept.append(article.id)
            continue
        article.status = ArticleStatus.DUPLICATE.value
        article.duplicate_of_article_id = original_id
        duplicate_count += 1
    session.commit()
    return kept, duplicate_count


def ingest_source(session: Session, source_id: int) -> IngestionStats:
    with timed_stage(logger, "ingestion.source_total", source_id=source_id):
        stats = discover_source(session, source_id)
        stats.extracted, stats.failed = extract_articles(session, stats.article_ids)
        _kept, content_duplicates = deduplicate_article_content(
            session, stats.article_ids
        )
        stats.duplicates += content_duplicates
        return stats


def discover_all_enabled_sources(session: Session) -> list[IngestionStats]:
    source_ids = session.scalars(
        select(Source.id)
        .join(Publisher, Publisher.id == Source.publisher_id)
        .where(Source.enabled.is_(True), Publisher.enabled.is_(True))
    ).all()
    results: list[IngestionStats] = []
    for source_id in source_ids:
        try:
            results.append(discover_source(session, source_id))
        except Exception as exc:
            session.rollback()
            logger.exception(
                "RSS source discovery failed; skipping source_id=%s", source_id
            )
            results.append(
                IngestionStats(source_id=source_id, error=str(exc)[:4000])
            )
    return results


async def discover_all_enabled_sources_async(
    session: Session, *, max_concurrency: int
) -> list[IngestionStats]:
    """Poll sources concurrently without sharing the caller's DB session."""
    source_ids = list(
        session.scalars(
            select(Source.id)
            .join(Publisher, Publisher.id == Source.publisher_id)
            .where(Source.enabled.is_(True), Publisher.enabled.is_(True))
        )
    )

    def discover_one(source_id: int) -> IngestionStats:
        with SessionLocal() as worker_session:
            try:
                return discover_source(worker_session, source_id)
            except Exception as exc:
                worker_session.rollback()
                logger.exception(
                    "RSS source discovery failed; skipping source_id=%s", source_id
                )
                return IngestionStats(source_id=source_id, error=str(exc)[:4000])

    return await bounded_to_thread_map(
        source_ids, discover_one, max_concurrency=max_concurrency
    )


async def extract_articles_async(
    article_ids: list[int], *, max_concurrency: int
) -> tuple[int, int]:
    """Extract independent articles concurrently using one session per worker."""
    unique_ids = list(dict.fromkeys(article_ids))

    def extract_one(article_id: int) -> tuple[int, int]:
        with SessionLocal() as worker_session:
            return extract_articles(worker_session, [article_id])

    results = await bounded_to_thread_map(
        unique_ids, extract_one, max_concurrency=max_concurrency
    )
    return sum(item[0] for item in results), sum(item[1] for item in results)


def ingest_all_enabled_sources(session: Session) -> list[IngestionStats]:
    stats = discover_all_enabled_sources(session)
    for source_stats in stats:
        if source_stats.error is not None:
            continue
        source_stats.extracted, source_stats.failed = extract_articles(
            session, source_stats.article_ids
        )
        _kept, content_duplicates = deduplicate_article_content(
            session, source_stats.article_ids
        )
        source_stats.duplicates += content_duplicates
    return stats
