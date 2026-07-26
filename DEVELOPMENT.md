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

## Publishers and category feeds

A publisher represents one website, while a source represents one RSS/Atom feed
owned by that publisher:

```text
The New Yorker
├── Latest feed
├── Politics feed
└── Culture feed
```

Important publisher attributes:

| Attribute | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Website or publication name. |
| `site_url` | No | Publisher homepage. Must be unique when provided. |
| `enabled` | No | Disabling it prevents scheduled fetching of all its feeds. |

Important source/feed attributes:

| Attribute | Required | Meaning |
| --- | --- | --- |
| `publisher_id` | Yes | Parent publisher ID. |
| `name` | Yes | Human-readable feed name. |
| `category` | No | Category such as `politics`, `culture`, or `latest`. |
| `feed_url` | Yes | Direct RSS or Atom URL, not a normal homepage. |
| `enabled` | No | Whether this individual feed is scheduled. |
| `poll_interval_minutes` | No | Stored preference; per-feed intervals are not yet scheduled separately. |

ETag, last-modified, polling timestamps, and creation timestamps are managed
automatically.

## Add a publisher and its feeds through FastAPI

The recommended method is http://127.0.0.1:8000/docs.

First use `POST /publishers`:

```json
{
  "name": "The New Yorker",
  "site_url": "https://www.newyorker.com/",
  "enabled": true
}
```

The response contains the publisher ID. Then use
`POST /publishers/{publisher_id}/sources` for each category feed:

```json
{
  "name": "The New Yorker Politics",
  "category": "politics",
  "feed_url": "https://example.com/replace-with-the-official-feed.xml",
  "enabled": true,
  "poll_interval_minutes": 30
}
```

Use `GET /publishers/{publisher_id}` to see the publisher and all its feeds.

`POST /sources` remains available for compatibility. Supply `publisher_id` to add
the feed to an existing publisher. When it is omitted, `site_url` is used to find or
create a publisher automatically.

## Add a source directly in pgAdmin

Direct SQL works, but it bypasses FastAPI URL validation.

Open pgAdmin's Query Tool for the `daily_reading` database and run:

```sql
INSERT INTO publishers (name, site_url, enabled)
VALUES ('BBC', 'https://www.bbc.com/news', true)
RETURNING id;
```

Use the returned publisher ID:

```sql
INSERT INTO sources (
    publisher_id,
    name,
    category,
    feed_url,
    enabled,
    poll_interval_minutes
)
VALUES (
    1,
    'BBC News',
    'latest',
    'https://feeds.bbci.co.uk/news/rss.xml',
    true,
    30
)
RETURNING id, name, feed_url;
```

`feed_url` must be unique. PostgreSQL generates IDs, usually 1, 2, 3, and so on,
but gaps are normal after failed inserts or deletions.

List sources and their IDs:

```sql
SELECT
    p.id AS publisher_id,
    p.name AS publisher,
    s.id AS source_id,
    s.name AS feed,
    s.category,
    s.feed_url,
    p.enabled AS publisher_enabled,
    s.enabled AS feed_enabled
FROM publishers AS p
JOIN sources AS s ON s.publisher_id = p.id
ORDER BY p.name, s.name;
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

Currently, APScheduler runs every `RSS_POLL_MINUTES` and fetches feeds only when both
their publisher and source `enabled` values are `true`. The individual
`sources.poll_interval_minutes` value is not yet consulted. Per-source scheduling
should be implemented separately before relying on different intervals.

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

## Phase 3 feedback and personalization

Phase 3 currently uses user `1` as the local default. Behavioral tables and daily
lists are already scoped by `user_id` so authentication can replace this development
identity later. The optional `X-User-ID` request header selects another existing
user, but it is not authentication and must not be exposed as security in deployment.

### Manual Phase 3 test

1. Generate a baseline list with `POST /daily-reading/generate`:

   ```json
   {
     "list_date": null,
     "regenerate": true
   }
   ```

2. Copy an `article.id` from the response. Record its `base_score`,
   `personalization_score`, and `total_score`.

3. Submit feedback with `POST /articles/{article_id}/feedback`:

   ```json
   {
     "event_type": "like",
     "reason": "good_writing"
   }
   ```

4. Call `GET /preferences/derived`. You should see learned publisher,
   content-type, category (when present), and topic features. One feedback event has
   deliberately low confidence; liking or disliking several related articles makes
   the preference stronger.

5. Generate the list again with `regenerate: true`. Compare
   `personalization_score` and `total_score` with the baseline. Articles sharing the
   learned features should move up or down.

6. Confirm the database state with the pgAdmin queries below. You can also call
   `GET /feedback` to verify the event history.

Submit feedback in FastAPI docs with `POST /articles/{article_id}/feedback`:

```json
{
  "event_type": "like",
  "reason": "good_writing"
}
```

Supported event types:

```text
like, dislike, skip, open, complete, star, unstar
```

Supported optional reasons:

```text
too_long, too_repetitive, strong_evidence, good_writing,
not_interested, too_technical
```

Useful feedback endpoints:

- `GET /feedback` returns recent feedback history.
- `GET /saved-articles` returns currently starred articles.
- `GET /preferences/derived` shows learned publisher, category, content-type, and
  topic features.

After submitting feedback, rebuild today's list with
`POST /daily-reading/generate`:

```json
{
  "list_date": null,
  "regenerate": true
}
```

The response includes `base_score`, `personalization_score`, and `total_score`.
Personalization is neutral until feedback produces matching derived features.

Inspect feedback and preferences in pgAdmin:

```sql
SELECT id, user_id, article_id, event_type, reason, created_at
FROM feedback_events
ORDER BY created_at DESC;
```

```sql
SELECT
    user_id,
    feature_type,
    feature_value,
    score,
    confidence,
    positive_count,
    negative_count
FROM preference_features
ORDER BY confidence DESC, score DESC;
```

```sql
SELECT
    dri.rank,
    a.title,
    dri.base_score,
    dri.personalization_score,
    dri.total_score,
    dri.selection_reason
FROM daily_reading_lists AS drl
JOIN daily_reading_items AS dri ON dri.reading_list_id = drl.id
JOIN articles AS a ON a.id = dri.article_id
WHERE drl.user_id = 1
ORDER BY drl.list_date DESC, dri.rank;
```

Explicit blocked-source preferences are intentionally deferred while discovery uses
only user-managed RSS feeds. They must be added before MCP or web-search discovery
can introduce sources outside the configured list.

## Execution-time logs

FastAPI now logs total HTTP request time and pipeline stage timing. Example:

```text
timing stage=daily.query_candidates status=ok elapsed_ms=9.34 user_id=1
timing stage=daily.classify_and_filter status=ok elapsed_ms=0.24 article_count=60
timing stage=daily.article_features status=ok elapsed_ms=16.05 article_count=47
timing stage=daily.score status=ok elapsed_ms=0.54 article_count=47
timing stage=daily.total status=ok elapsed_ms=42.39 user_id=1
timing stage=http.request status_code=200 elapsed_ms=48.10 method=POST path=/daily-reading/generate
```

RSS ingestion logs `ingestion.fetch_rss`, `ingestion.extract_article`, and
`ingestion.source_total`. Feedback logs saved-state, article-feature, preference
rebuild, and total execution time. Failed stages are logged with `status=error`.

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
