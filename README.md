# Daily Reading Agent

Phase 1 collects RSS entries, extracts full article text, and stores it in PostgreSQL.
Phase 2 filters and scores extracted articles and saves a deterministic daily list.
Phase 3 records user feedback and uses derived preferences to personalize later lists.
Publishers group multiple category feeds under one website-level source selection.
Phase 4 runs those stages as a checkpointed LangGraph workflow with bounded expansion,
per-node timing, failure history, and resume support.
Phase 5 adds provider-separated AI classification, Qwen embeddings, pgvector story
clustering, DeepSeek claim extraction and evidence comparison, and deterministic
representative-article selection.

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
