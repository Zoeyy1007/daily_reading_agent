import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import (
    agent_runs,
    analytics,
    articles,
    auth,
    daily_reading,
    evidence,
    feedback,
    ingestion,
    publishers,
    sources,
    supplements,
)
from app.config import get_settings
from app.db.session import engine
from app.services.scheduler_service import start_scheduler, stop_scheduler

application_logger = logging.getLogger("daily_reading")
application_logger.setLevel(get_settings().log_level.upper())
if not application_logger.handlers:
    application_handler = logging.StreamHandler()
    application_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    application_logger.addHandler(application_handler)
application_logger.propagate = False
http_logger = logging.getLogger("daily_reading.http")
static_directory = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().scheduler_enabled:
        start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(sources.router)
app.include_router(publishers.router)
app.include_router(articles.router)
app.include_router(ingestion.router)
app.include_router(daily_reading.router)
app.include_router(feedback.router)
app.include_router(agent_runs.router)
app.include_router(evidence.router)
app.include_router(supplements.router)
app.mount("/static", StaticFiles(directory=static_directory), name="static")


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        http_logger.info(
            "timing stage=http.request status_code=%s elapsed_ms=%.2f method=%s path=%s",
            status_code,
            elapsed_ms,
            request.method,
            request.url.path,
        )


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(static_directory / "index.html")
