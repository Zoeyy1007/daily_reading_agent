# Daily Reading Agent

Phase 1 collects RSS entries, extracts full article text, and stores it in PostgreSQL.

## Run locally

```powershell
docker compose up -d db
.\venv\Scripts\Activate.ps1
alembic upgrade head
fastapi dev app/main.py
```

Open `http://127.0.0.1:8000/docs`, add a source with `POST /sources`, then run
`POST /sources/{source_id}/fetch`.

See [DEVELOPMENT.md](DEVELOPMENT.md) for source management, pgAdmin queries,
manual ingestion, and scheduler instructions.

Set `SCHEDULER_ENABLED=true` in `.env` to enable periodic ingestion. Keep it false
while using a reload server if you want to avoid scheduler restarts during edits.
