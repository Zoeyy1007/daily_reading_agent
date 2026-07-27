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

Prefer disabling a broken feed first because deleting a source also deletes its
articles through the database cascade. In FastAPI docs, call
`PATCH /sources/{source_id}` with:

```json
{
  "enabled": false
}
```

To permanently remove it, call `DELETE /sources/{source_id}`. Bulk ingestion and
agent collection isolate feed-level errors: a failed feed is logged, returned with
an `error` value, counted in `source_failures`, and skipped while other feeds
continue.

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

## Phase 4 stateful agent runs

Install the Phase 4 dependencies and apply the migration:

```powershell
python -m pip install -r requirements-dev.txt
alembic upgrade head
```

Set these values in `.env` and restart FastAPI:

```dotenv
AGENT_MAX_EXPANSION_ROUNDS=3
AGENT_RECURSION_LIMIT=40
AGENT_RUN_IN_BACKGROUND=true
LANGGRAPH_STRICT_MSGPACK=true
```

No AI API key is required for Phase 4. Classification, embedding, claim extraction,
and evidence comparison have separate provider interfaces and model settings so they
can use different models later. Provider clients and secrets are never stored in
checkpoint state.

### Start an agent run

In FastAPI docs, call `POST /agent/runs`:

```json
{
  "list_date": null,
  "regenerate": true,
  "background": true,
  "max_expansion_rounds": 3
}
```

The API normally returns `202` immediately. Copy the returned `id`, then poll:

```text
GET /agent/runs/{run_id}
GET /agent/runs/{run_id}/events
```

For easier debugging, set `background` to `false`. The request will wait until the
whole graph finishes, so the Swagger request may take a while when feeds contain many
new articles.

If a run has status `failed`, fix the underlying problem and call:

```text
POST /agent/runs/{run_id}/resume?background=true
```

Resume uses the same `thread_id` and continues from the latest PostgreSQL checkpoint.
Successful earlier nodes are not started again. A PostgreSQL advisory lock prevents
two local workers from executing the same run concurrently.

Expansion is bounded:

1. Round 0 uses newly discovered articles from configured feeds.
2. Round 1 adds extracted candidates already in PostgreSQL.
3. Round 2 records that related web search is unavailable until a search provider is configured.
4. Round 3 keeps hard filters and records that no separate soft threshold exists yet.

### Inspect agent runs in pgAdmin

```sql
SELECT
    id,
    thread_id,
    user_id,
    list_date,
    status,
    current_node,
    expansion_round,
    selected_count,
    reading_list_id,
    last_error,
    started_at,
    completed_at
FROM daily_runs
ORDER BY created_at DESC;
```

View timings and errors for one run:

```sql
SELECT
    node_name,
    attempt,
    status,
    elapsed_ms,
    message,
    started_at,
    completed_at
FROM run_events
WHERE run_id = 1
ORDER BY id;
```

LangGraph creates its own checkpoint tables when the first run calls
`PostgresSaver.setup()`. Treat those as internal workflow tables. Use `daily_runs`
and `run_events` for normal inspection.

Run only Phase 4 tests:

```powershell
python -m pytest tests/test_phase_four.py -q
```

These tests cover termination routing, reading-budget selection, and resuming after a
simulated mid-graph failure without repeating successful nodes.

## Phase 5 story and evidence pipeline

Phase 5 runs inside the agent graph after deterministic filtering:

```text
AI classification -> article embeddings -> story clustering -> redundancy pruning
-> chunks -> hybrid retrieval -> claim extraction -> bounded pair comparison
-> representative selection
```

Each model role is configured independently. Copy the Phase 5 block from
`.env.example` into `.env`, add your real keys there, and keep `.env` out of Git.
The current MVP uses Qwen for 1024-dimensional embeddings and DeepSeek for
classification, claim extraction, and evidence comparison. Kimi remains an optional
evidence provider selected with `EVIDENCE_COMPARISON_PROVIDER=kimi`.

Install dependencies and create the pgvector tables:

```powershell
python -m pip install -r requirements-dev.txt
alembic upgrade head
```

PostgreSQL's `vector` extension is enabled by the migration. Do not change
`EMBEDDING_DIMENSIONS` without a new migration because the database columns are
currently `vector(1024)`.

### Run Phase 5

Start FastAPI, then use `POST /agent/runs` in the API docs:

```json
{
  "list_date": null,
  "regenerate": true,
  "background": false,
  "max_expansion_rounds": 3
}
```

Synchronous mode is easiest to debug, but it can take several minutes because the
models are called sequentially. For normal use, set
`background` to `true`, copy the returned run ID, and poll:

```text
GET /agent/runs/{run_id}
GET /agent/runs/{run_id}/events
GET /evidence/model-calls
```

The model-call endpoint shows provider, model, token counts, execution time, and
errors without exposing API keys or full prompts.

### Inspect one completed agent run

Replace `5` below with the run ID returned by `POST /agent/runs`.

Useful API requests in FastAPI docs:

```text
GET  /agent/runs/5
GET  /agent/runs/5/events
GET  /daily-reading/today
GET  /evidence/model-calls?run_id=5
GET  /evidence/clusters
GET  /evidence/clusters/{cluster_id}
```

PowerShell equivalents for the run and its events:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/agent/runs/5
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/agent/runs/5/events
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/daily-reading/today
```

To start another run or resume a failed one:

```powershell
$body = @{
    list_date = $null
    regenerate = $true
    background = $true
    max_expansion_rounds = 3
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/agent/runs `
    -ContentType "application/json" `
    -Body $body

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/agent/runs/5/resume?background=true"
```

View the final reading list produced by one run in pgAdmin:

```sql
SELECT
    dr.id AS run_id,
    dr.status AS run_status,
    drl.id AS reading_list_id,
    drl.list_date,
    dri.rank,
    a.id AS article_id,
    a.title,
    a.word_count,
    dri.total_score,
    dri.reading_minutes,
    a.canonical_url
FROM daily_runs AS dr
JOIN daily_reading_lists AS drl ON drl.id = dr.reading_list_id
JOIN daily_reading_items AS dri ON dri.reading_list_id = drl.id
JOIN articles AS a ON a.id = dri.article_id
WHERE dr.id = 5
ORDER BY dri.rank;
```

See every node attempt, including failures followed by successful resumes:

```sql
SELECT
    node_name,
    attempt,
    status,
    elapsed_ms,
    message,
    started_at,
    completed_at
FROM run_events
WHERE run_id = 5
ORDER BY id;
```

Summarize how many model requests and tokens each role used:

```sql
SELECT
    role,
    provider,
    model,
    status,
    COUNT(*) AS request_count,
    COALESCE(SUM(input_tokens), 0) AS input_tokens,
    COALESCE(SUM(output_tokens), 0) AS output_tokens,
    ROUND(COALESCE(SUM(elapsed_ms), 0)::numeric, 1) AS elapsed_ms
FROM model_calls
WHERE run_id = 5
GROUP BY role, provider, model, status
ORDER BY role, status;
```

See the number of claims extracted from each article during the run:

```sql
SELECT
    ac.cluster_id,
    ac.article_id,
    a.title,
    COUNT(*) AS extracted_claims
FROM article_claims AS ac
JOIN articles AS a ON a.id = ac.article_id
JOIN daily_runs AS dr
  ON ac.created_at BETWEEN dr.started_at AND dr.completed_at
WHERE dr.id = 5
GROUP BY ac.cluster_id, ac.article_id, a.title
ORDER BY ac.cluster_id, ac.article_id;
```

Inspect chunks belonging to those claim-extraction articles:

```sql
WITH run_articles AS (
    SELECT DISTINCT ac.article_id, ac.cluster_id
    FROM article_claims AS ac
    JOIN daily_runs AS dr
      ON ac.created_at BETWEEN dr.started_at AND dr.completed_at
    WHERE dr.id = 5
)
SELECT
    ra.cluster_id,
    ch.article_id,
    a.title,
    ch.chunk_index,
    ch.word_count,
    LEFT(ch.chunk_text, 500) AS chunk_preview,
    vector_dims(ch.embedding) AS embedding_dimensions
FROM run_articles AS ra
JOIN article_chunks AS ch ON ch.article_id = ra.article_id
JOIN articles AS a ON a.id = ch.article_id
ORDER BY ra.cluster_id, ch.article_id, ch.chunk_index;
```

Count the claim pairs actually evaluated and saved by evidence comparison:

```sql
SELECT
    cl.cluster_id,
    cl.relationship,
    COUNT(*) AS evaluated_pairs
FROM claim_links AS cl
JOIN daily_runs AS dr
  ON cl.created_at BETWEEN dr.started_at AND dr.completed_at
WHERE dr.id = 5
GROUP BY cl.cluster_id, cl.relationship
ORDER BY cl.cluster_id, cl.relationship;
```

The database stores all chunks, extracted claims, evaluated claim links, and model
token totals. The current hybrid BM25/vector top-chunk ranking is computed in memory,
so it does not yet preserve an exact historical list of selected chunk IDs. When an
article has more chunks than the retrieval limit, the chunk query above shows the
candidate pool rather than proving every row was sent to claim extraction. Phase 6
should persist its selected supplemental evidence and citations so its exact inputs
remain inspectable after a run.

### View clusters and evidence

Use these FastAPI endpoints:

```text
GET /evidence/clusters
GET /evidence/clusters/{cluster_id}
```

The detail response contains cluster members, extracted claims, cross-report links,
the representative article, and its selection explanation.

Cluster membership is bounded before paid claim work. The system keeps at most five
articles using article-embedding relevance, novelty, and publisher diversity.
Members marked `redundant` remain visible for auditing but do not proceed to claim
extraction or final selection.

Every retained article is represented by at least one chunk. Okapi BM25 lexical
scores and vector cosine scores are normalized and combined with configurable
weights. At most 20 chunks continue to claim extraction. After DeepSeek extracts
claims, a second retrieval stage keeps at most 20 cross-publisher claim pairs. The
configured evidence provider receives those explicit pairs in batches of five; it
never receives the old flat 60-claim request.

Useful pgAdmin queries:

```sql
SELECT
    sc.id,
    sc.representative_title,
    sc.representative_article_id,
    sc.comparison_status,
    COUNT(scm.id) AS member_count,
    sc.expires_at
FROM story_clusters AS sc
JOIN story_cluster_members AS scm ON scm.cluster_id = sc.id
GROUP BY sc.id
ORDER BY sc.created_at DESC;
```

```sql
SELECT
    ac.cluster_id,
    ac.article_id,
    a.title,
    ac.claim_text,
    ac.claim_type,
    ac.supporting_excerpt,
    ac.confidence
FROM article_claims AS ac
JOIN articles AS a ON a.id = ac.article_id
ORDER BY ac.cluster_id DESC, ac.article_id, ac.id;
```

```sql
SELECT
    cl.cluster_id,
    left_claim.claim_text AS left_claim,
    right_claim.claim_text AS right_claim,
    cl.relationship,
    cl.confidence,
    cl.rationale
FROM claim_links AS cl
JOIN article_claims AS left_claim ON left_claim.id = cl.left_claim_id
JOIN article_claims AS right_claim ON right_claim.id = cl.right_claim_id
ORDER BY cl.cluster_id DESC, cl.id;
```

```sql
SELECT
    cc.cluster_id,
    a.title AS selected_article,
    cc.shared_claim_count,
    cc.disputed_claim_count,
    cc.selection_reason,
    cc.model,
    cc.expires_at
FROM cluster_comparisons AS cc
JOIN articles AS a ON a.id = cc.representative_article_id
ORDER BY cc.created_at DESC;
```

Only clusters containing reports from at least two different publishers proceed to
evidence comparison. Separate category feeds owned by the same publisher do not
count as independent corroboration. Short articles become one chunk; long articles
are chunked with overlap. Unselected intermediate evidence defaults to seven days.
Evidence for articles selected into a daily list is extended to 30 days, which is
also the hard configuration maximum for the MVP.

After changing clustering, retrieval, or prompt settings, create a new agent run.
Do not resume an older failed run because LangGraph resume continues from its saved
node and intentionally does not repeat completed chunk/retrieval stages.

Run Phase 5 tests:

```powershell
python -m pytest tests/test_phase_five.py -q
```

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
