import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Article, ArticleStatus, Publisher, Source
from app.services.article_extractor import ArticleExtractor, ExtractionFailedError
from app.sources.rss import RSSItem, fetch_rss
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


def _ingest_source(session: Session, source_id: int) -> IngestionStats:
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

        extractor = ArticleExtractor(
            client,
            minimum_words=settings.article_min_words,
            jina_api_key=settings.jina_api_key,
        )
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

            article.status = ArticleStatus.EXTRACTING.value
            session.commit()
            try:
                with timed_stage(
                    logger,
                    "ingestion.extract_article",
                    source_id=source_id,
                    article_id=article.id,
                ):
                    extracted = extractor.extract(canonical_url)
                article.content_text = extracted.content
                article.author = extracted.author or article.author
                article.title = extracted.title or article.title
                article.word_count = extracted.word_count
                article.content_hash = extracted.content_hash
                article.extractor_used = extracted.extractor
                article.fetched_at = extracted.fetched_at
                article.status = ArticleStatus.EXTRACTED.value
                article.extraction_error = None
                stats.extracted += 1
            except ExtractionFailedError as exc:
                article.status = ArticleStatus.FAILED.value
                article.fetched_at = datetime.now(UTC)
                article.extraction_error = str(exc)[:4000]
                stats.failed += 1
            session.commit()

        source.last_success_at = datetime.now(UTC)
        session.commit()
    return stats


def ingest_source(session: Session, source_id: int) -> IngestionStats:
    with timed_stage(logger, "ingestion.source_total", source_id=source_id):
        return _ingest_source(session, source_id)


def ingest_all_enabled_sources(session: Session) -> list[IngestionStats]:
    source_ids = session.scalars(
        select(Source.id)
        .join(Publisher, Publisher.id == Source.publisher_id)
        .where(Source.enabled.is_(True), Publisher.enabled.is_(True))
    ).all()
    return [ingest_source(session, source_id) for source_id in source_ids]
