import calendar
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from urllib.parse import urljoin

import feedparser
import httpx


@dataclass(slots=True)
class RSSItem:
    guid: str | None
    url: str
    title: str
    summary: str | None
    author: str | None
    published_at: datetime | None


@dataclass(slots=True)
class RSSFetchResult:
    items: list[RSSItem]
    etag: str | None
    last_modified: str | None
    not_modified: bool = False


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = " ".join(html.unescape(without_tags).split())
    return normalized or None


def _parsed_datetime(value: struct_time | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)


def fetch_rss(
    feed_url: str,
    *,
    client: httpx.Client,
    etag: str | None = None,
    last_modified: str | None = None,
) -> RSSFetchResult:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    response = client.get(feed_url, headers=headers)
    if response.status_code == httpx.codes.NOT_MODIFIED:
        return RSSFetchResult([], etag, last_modified, not_modified=True)
    response.raise_for_status()

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Invalid RSS/Atom feed: {parsed.bozo_exception}")

    items: list[RSSItem] = []
    for entry in parsed.entries:
        raw_url = entry.get("link")
        if not raw_url:
            continue
        guid = str(entry.get("id") or entry.get("guid") or "").strip() or None
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        items.append(
            RSSItem(
                guid=guid,
                url=urljoin(str(response.url), raw_url),
                title=_plain_text(entry.get("title")) or "Untitled",
                summary=_plain_text(entry.get("summary") or entry.get("description")),
                author=_plain_text(entry.get("author")),
                published_at=_parsed_datetime(published),
            )
        )

    return RSSFetchResult(
        items=items,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
    )
