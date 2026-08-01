"""Re-extract one stored article without changing its database row.

This is intended for checking extraction changes against a real article URL.
The newly extracted text is written to a local report for comparison with the
existing ``articles.content_text`` value.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.models import Article  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.article_extractor import (  # noqa: E402
    ArticleExtractor,
    ExtractionFailedError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-extract one database article without updating the database."
    )
    parser.add_argument("--article-id", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output text file (default: metrics/results/article_<id>_extraction.txt)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Allow Jina's cached response. Fresh Jina content is requested by default.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()

    with SessionLocal() as session:
        article = session.get(Article, args.article_id)
        if article is None:
            print(f"Article {args.article_id} was not found.", file=sys.stderr)
            return 1
        article_id = article.id
        title = article.title
        url = article.canonical_url
        source_id = article.source_id
        existing_extractor = article.extractor_used
        existing_word_count = article.word_count

    output = args.output or (
        PROJECT_ROOT / "metrics" / "results" / f"article_{article_id}_extraction.txt"
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Testing article_id={article_id} source_id={source_id}", flush=True)
    print(f"Title: {title}", flush=True)
    print(f"URL: {url}", flush=True)
    print(
        f"Stored extraction: extractor={existing_extractor or 'none'} "
        f"words={existing_word_count or 0}",
        flush=True,
    )
    print("Fetching and extracting a fresh copy...", flush=True)

    timeout = httpx.Timeout(settings.http_timeout_seconds)
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            result = ArticleExtractor(
                client,
                minimum_words=settings.article_min_words,
                jina_api_key=settings.jina_api_key,
                jina_no_cache=not args.use_cache,
            ).extract(url, title=title)
    except ExtractionFailedError as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 2

    report = (
        f"Article ID: {article_id}\n"
        f"Source ID: {source_id}\n"
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Stored extractor: {existing_extractor or 'none'}\n"
        f"Stored word count: {existing_word_count or 0}\n"
        f"Test extractor: {result.extractor}\n"
        f"Test word count: {result.word_count}\n"
        "\n--- CLEANED CONTENT ---\n\n"
        f"{result.content}\n"
    )
    output.write_text(report, encoding="utf-8")
    print(
        f"Complete: extractor={result.extractor} words={result.word_count}", flush=True
    )
    print(f"Wrote cleaned output to {output}", flush=True)
    print("The database was not modified.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
