# Railway and Supabase deployment

This deployment uses:

- Railway for the FastAPI application and static frontend.
- Supabase for PostgreSQL and pgvector.
- Railway service variables for secrets. No API key belongs in Git, the
  `Dockerfile`, or `railway.json`.

The repository already contains the deployment files:

- `Dockerfile` installs the locked Python dependencies and starts one Uvicorn
  worker on Railway's injected `PORT`.
- `railway.json` runs `alembic upgrade head` before each deployment and checks
  `/health` before accepting traffic.
- `.dockerignore` prevents local secrets, database dumps, tests, and metrics
  from entering the image.

## 1. Move the local database to the empty Supabase project

Do this before the first successful Railway deployment. Otherwise Alembic will
create empty application tables in Supabase and the full restore will conflict
with them.

### Get the correct Supabase connection

In Supabase, open **Connect** (or **Project Settings → Database**) and copy the
**Session pooler** connection string on port `5432`. Use session mode for both
the migration and the running application. Do not use transaction mode on port
`6543` for this app.

The URL should resemble:

```text
postgresql://postgres.PROJECT_REF:PASSWORD@REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

Use the connection string supplied by Supabase. If you insert the password
manually, URL-encode special characters in it.

### Enable pgvector

In Supabase's SQL Editor, run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Stop local writes and create a dump

Stop the local FastAPI process before dumping. Leave the local Docker database
running, then run these commands from the repository root in PowerShell:

```powershell
docker compose exec db pg_dump `
  --username=daily_reading `
  --dbname=daily_reading `
  --format=custom `
  --schema=public `
  --no-owner `
  --no-privileges `
  --no-subscriptions `
  --verbose `
  --file=/tmp/daily_reading.dump

docker cp daily-reading-db:/tmp/daily_reading.dump .\daily_reading.dump
```

The dump contains your users, password hashes, articles, preferences, reading
lists, model records, LangGraph checkpoints, and Alembic revision. It is ignored
by Git but should still be treated as private data.

### Restore the dump

Paste the Session pooler URL only when PowerShell prompts for it:

```powershell
$env:SUPABASE_DB_URL = Read-Host "Paste the Supabase Session pooler URL"

docker compose exec -e "SUPABASE_DB_URL=$env:SUPABASE_DB_URL" db sh -lc `
  'pg_restore --dbname="$SUPABASE_DB_URL" --jobs=2 --no-owner --no-privileges --verbose /tmp/daily_reading.dump'
```

An extension-related notice can be harmless if `vector` is already installed,
but table, constraint, sequence, or data errors are not. Inspect the final
`pg_restore` output before continuing.

Update statistics and verify the restored tables:

```powershell
docker compose exec -e "SUPABASE_DB_URL=$env:SUPABASE_DB_URL" db sh -lc `
  'psql "$SUPABASE_DB_URL" -c "VACUUM ANALYZE;"'

docker compose exec -e "SUPABASE_DB_URL=$env:SUPABASE_DB_URL" db sh -lc `
  'psql "$SUPABASE_DB_URL" -c "SELECT version_num FROM alembic_version; SELECT count(*) AS articles FROM articles; SELECT count(*) AS users FROM users;"'

Remove-Item Env:SUPABASE_DB_URL
```

Also inspect **Supabase → Table Editor**. Once the restore is confirmed, securely
store or remove `daily_reading.dump`; never commit or upload it as a build asset.

## 2. Create the Railway service

1. In Railway, create a new project and choose **Deploy from GitHub repo**.
2. Select this repository. Railway detects the root `Dockerfile`.
3. Open the service's **Variables** tab and add the variables below.
4. In service settings, keep **one replica**. The app intentionally uses one
   Uvicorn worker because it contains an in-process scheduler and background
   agent runs.
5. Deploy the staged variable/config changes.
6. In **Settings → Networking**, generate a Railway public domain.
7. Open `https://YOUR-DOMAIN/health`; it should return `{"status":"ok"}`.

The pre-deploy migration uses the same `DATABASE_URL`. If it fails, Railway will
not start the new application deployment.

## 3. Railway variables and API keys

At minimum, add these in Railway's **Variables** tab. Values below are names or
examples only—paste real secrets directly into Railway.

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT_REF:PASSWORD@REGION.pooler.supabase.com:5432/postgres?sslmode=require
LOG_LEVEL=INFO
AUTH_COOKIE_SECURE=true
SCHEDULER_ENABLED=false
SCHEDULER_TIMEZONE=America/Los_Angeles
DAILY_LIST_HOUR=8

PHASE_FIVE_ENABLED=true
EMBEDDING_PROVIDER=qwen
EMBEDDING_MODEL=text-embedding-v4
DASHSCOPE_API_KEY=replace_in_railway
QWEN_BASE_URL=replace_with_your_current_qwen_endpoint

CLASSIFICATION_PROVIDER=deepseek
CLASSIFICATION_MODEL=deepseek-v4-flash
CLAIM_EXTRACTION_PROVIDER=deepseek
CLAIM_EXTRACTION_MODEL=deepseek-v4-pro
EVIDENCE_COMPARISON_PROVIDER=deepseek
EVIDENCE_COMPARISON_MODEL=deepseek-v4-pro
DEEPSEEK_API_KEY=replace_in_railway
DEEPSEEK_BASE_URL=https://api.deepseek.com

PHASE_SIX_ENABLED=true
SUPPLEMENT_MODEL=deepseek-v4-pro
SUPPLEMENT_PLANNING_MAX_ATTEMPTS=3
SUPPLEMENT_VERIFICATION_MAX_ATTEMPTS=3
TAVILY_API_KEY=replace_in_railway
TAVILY_BASE_URL=https://api.tavily.com
TAVILY_SEARCH_DEPTH=none
```

Copy any non-secret tuning values you changed in your local `.env` as well. Do
not add `PORT`; Railway supplies it. `POSTGRES_PASSWORD` is only for the local
Docker database and is not needed by the Railway service.

Optional secrets are needed only when their provider is actually configured:

- `MOONSHOT_API_KEY` for Kimi/Moonshot roles.
- `JINA_API_KEY` for the optional Jina extraction fallback.

You do **not** need Supabase's anon key or service-role key. This application
uses its own login system and talks directly to PostgreSQL through
`DATABASE_URL`.

## 4. Scheduler rollout

Leave `SCHEDULER_ENABLED=false` during deployment testing, as it is now. Manually
run ingestion and agent generation through the existing API first.

When ready for automatic execution:

1. Confirm the Railway service has one replica.
2. Set `SCHEDULER_ENABLED=true` in Railway.
3. Deploy the variable change.
4. Check Railway logs for scheduler, ingestion, and agent timing messages.

The configured daily run is 08:00 in `America/Los_Angeles`, including daylight
saving changes. PostgreSQL advisory locks prevent overlapping service processes
from running the same scheduled job simultaneously.

## 5. Deployment checks

After each deployment, verify:

```text
GET /health
GET /
POST /auth/login
GET /daily-reading/today
```

Then check Railway logs and Supabase's Table Editor. If `/health` fails, check
the Railway deployment logs first; it normally means `DATABASE_URL`, SSL,
networking, or the pre-deploy migration needs attention.
