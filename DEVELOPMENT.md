# Daily Reading Development Guide

## Start the application

Open PowerShell in the project directory and activate the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

Start PostgreSQL:

```powershell
docker compose up -d db
docker compose ps
```

Apply database migrations:

```powershell
alembic upgrade head
```

Start FastAPI and leave this terminal open:

```powershell
fastapi dev app/main.py
```

Useful addresses:

- API documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

Use a second PowerShell terminal for manual API commands.

## Source attributes

The `sources` table contains:

| Attribute | Required when adding | Meaning |
| --- | --- | --- |
| `id` | No | Database-generated numeric identifier. |
| `name` | Yes | Human-readable source name. |
| `feed_url` | Yes | Direct RSS or Atom feed URL. It must not be a normal homepage. |
| `site_url` | No | Website homepage for reference only. |
| `enabled` | No | Whether scheduled ingestion includes this source. Defaults to `true`. |
| `poll_interval_minutes` | No | Stored source preference. The current scheduler does not use this field yet. |
| `etag` | No | Saved automatically for conditional RSS requests. |
| `last_modified` | No | Saved automatically for conditional RSS requests. |
| `last_polled_at` | No | Updated automatically after a polling attempt. |
| `last_success_at` | No | Updated automatically after successful feed processing. |
| `created_at` | No | Set automatically. |
| `updated_at` | No | Set automatically. |

## Add a source through FastAPI

The recommended method is http://127.0.0.1:8000/docs using `POST /sources`.

Example request:

```json
{
  "name": "BBC News",
  "feed_url": "https://feeds.bbci.co.uk/news/rss.xml",
  "site_url": "https://www.bbc.com/news",
  "enabled": true,
  "poll_interval_minutes": 30
}
```

Only `name` and `feed_url` are required.

PowerShell alternative:

```powershell
$body = @{
    name = "BBC News"
    feed_url = "https://feeds.bbci.co.uk/news/rss.xml"
    site_url = "https://www.bbc.com/news"
    enabled = $true
    poll_interval_minutes = 30
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/sources `
    -ContentType "application/json" `
    -Body $body
```

The response includes the generated source `id`.

## Add a source directly in pgAdmin

Direct SQL works, but it bypasses FastAPI URL validation.

Open pgAdmin's Query Tool for the `daily_reading` database and run:

```sql
INSERT INTO sources (
    name,
    feed_url,
    site_url,
    enabled,
    poll_interval_minutes
)
VALUES (
    'BBC News',
    'https://feeds.bbci.co.uk/news/rss.xml',
    'https://www.bbc.com/news',
    true,
    30
)
RETURNING id, name, feed_url;
```

`feed_url` must be unique. PostgreSQL generates IDs, usually 1, 2, 3, and so on,
but gaps are normal after failed inserts or deletions.

List sources and their IDs:

```sql
SELECT id, name, feed_url, enabled, last_polled_at, last_success_at
FROM sources
ORDER BY id;
```

Enable or disable a source:

```sql
UPDATE sources SET enabled = false WHERE id = 1;
UPDATE sources SET enabled = true WHERE id = 1;
```

## Fetch articles manually

Use the source ID returned when the source was created:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/sources/1/fetch
```

The result reports discovered, extracted, failed, and duplicate counts.

Fetch every enabled source:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/ingestion/run
```

Manual fetches run immediately and do not wait for the scheduler.

## Automatic polling

Configure `.env`:

```dotenv
SCHEDULER_ENABLED=true
RSS_POLL_MINUTES=30
```

Restart FastAPI after changing `.env`.

Currently, APScheduler runs every `RSS_POLL_MINUTES` and fetches every source whose
`enabled` value is `true`. The individual `sources.poll_interval_minutes` value is
not yet consulted. Per-source scheduling should be implemented separately before
relying on different polling intervals for different feeds.

Keep only one FastAPI process running with the scheduler enabled. Multiple server
workers could each start a scheduler and fetch the same feeds concurrently.

RSS `ETag` and `Last-Modified` values are saved. When supported by the publisher,
unchanged feeds return `304 Not Modified`, avoiding unnecessary processing.

## Configure Phase 2 daily lists

Phase 2 uses deterministic filtering and scoring. Configure it in `.env`:

```dotenv
MIN_ARTICLE_WORDS=200
MAX_ARTICLE_WORDS=4000
MAX_ARTICLE_AGE_HOURS=48
ALLOWED_LANGUAGES=en
ALLOWED_CONTENT_TYPES=news,analysis,opinion,tutorial,other
PREFERRED_TOPICS=technology,science
PREFERRED_SOURCE_IDS=
BLOCKED_SOURCE_IDS=
DAILY_ARTICLE_TARGET=5
DAILY_READING_MINUTES=30
READING_WORDS_PER_MINUTE=225
DAILY_LIST_HOUR=7
SCHEDULER_TIMEZONE=America/Los_Angeles
```

Comma-separated source settings use numeric source IDs, for example:

```dotenv
PREFERRED_SOURCE_IDS=1,3
BLOCKED_SOURCE_IDS=4
```

Restart FastAPI after changing `.env`.

The score has four explicit components:

- Freshness: 0 to 40 points.
- Preferred-topic matches: 0 to 30 points.
- Source preference: 0 to 20 points.
- Length fit: 0 to 10 points.

If no preferred topics or sources are configured, neutral topic and source scores
are used so freshness and length still determine the ordering.

## Generate and view a daily reading list

Make sure PostgreSQL and FastAPI are running first:

```powershell
docker compose up -d db
fastapi dev app/main.py
```

In FastAPI docs, use `POST /daily-reading/generate` with:

```json
{
  "list_date": null,
  "regenerate": false
}
```

A null date means today in `SCHEDULER_TIMEZONE`. Generating the same date again
returns the existing list. Set `regenerate` to `true` to rebuild it using current
articles and settings.

To manually rebuild today's list, use:

```json
{
  "list_date": null,
  "regenerate": true
}
```

PowerShell alternative:

```powershell
$body = @{
    list_date = $null
    regenerate = $false
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/daily-reading/generate `
    -ContentType "application/json" `
    -Body $body
```

Other endpoints:

- `GET /daily-reading/today`
- `GET /daily-reading/{list_date}`, such as `/daily-reading/2026-07-25`

When scheduling is enabled, a list is regenerated each day at `DAILY_LIST_HOUR` in
`SCHEDULER_TIMEZONE`.

### Inspect the generated list in pgAdmin

First view the list-level record:

```sql
SELECT
    id,
    list_date,
    target_article_count,
    target_reading_minutes,
    actual_article_count,
    actual_reading_minutes,
    status,
    created_at
FROM daily_reading_lists
ORDER BY list_date DESC;
```

View the selected articles and their scores:

```sql
SELECT
    drl.id AS reading_list_id,
    drl.list_date,
    dri.rank,
    a.id AS article_id,
    a.title,
    dri.total_score,
    dri.freshness_score,
    dri.topic_score,
    dri.source_score,
    dri.length_score,
    dri.reading_minutes,
    dri.selection_reason
FROM daily_reading_lists AS drl
JOIN daily_reading_items AS dri ON dri.reading_list_id = drl.id
JOIN articles AS a ON a.id = dri.article_id
ORDER BY drl.list_date DESC, dri.rank;
```

View the full content for the articles in the newest list:

```sql
SELECT
    dri.rank,
    a.title,
    a.canonical_url,
    a.content_text
FROM daily_reading_lists AS drl
JOIN daily_reading_items AS dri ON dri.reading_list_id = drl.id
JOIN articles AS a ON a.id = dri.article_id
WHERE drl.list_date = (SELECT MAX(list_date) FROM daily_reading_lists)
ORDER BY dri.rank;
```

## Run tests

Activate the virtual environment and install development dependencies once:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Run all tests:

```powershell
python -m pytest -q
```

Run only the Phase 2 tests:

```powershell
python -m pytest tests/test_phase_two.py -q
```

Run one test by name:

```powershell
python -m pytest tests/test_phase_two.py::test_scoring_rewards_fresh_topic_and_preferred_source -q
```

Run the tests with a coverage report:

```powershell
python -m pytest --cov=app --cov-report=term-missing
```

## View fetched articles in pgAdmin

Open `Schemas -> public -> Tables -> articles`, then select
`View/Edit Data -> All Rows`.

Article overview query:

```sql
SELECT
    id,
    source_id,
    title,
    status,
    extractor_used,
    word_count,
    language,
    content_type,
    published_at,
    canonical_url
FROM articles
ORDER BY created_at DESC;
```

View the full content of one article:

```sql
SELECT title, content_text
FROM articles
WHERE id = 1;
```

Inspect extraction failures:

```sql
SELECT id, title, canonical_url, extraction_error
FROM articles
WHERE status = 'failed'
ORDER BY created_at DESC;
```

## RSS feeds versus website homepages

The current collector accepts RSS or Atom feeds. It does not crawl a website
homepage or automatically discover every category page.

A general BBC feed contains only the entries published in that feed. If BBC has a
separate technology, business, world, or sports RSS feed, add each desired feed as
a separate source. This gives each category its own source ID and deduplication still
prevents the same article URL from being stored twice.

Before adding a URL, open it in a browser and confirm it displays RSS/XML rather than
a normal HTML webpage.

## Stop development services

Stop FastAPI with `Ctrl+C` in its terminal.

Stop PostgreSQL without deleting its data:

```powershell
docker compose stop db
```

Start it again later with:

```powershell
docker compose up -d db
```
