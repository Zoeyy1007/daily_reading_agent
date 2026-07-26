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
