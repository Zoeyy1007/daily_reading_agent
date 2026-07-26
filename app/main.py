from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import text

from app.api import articles, daily_reading, ingestion, sources
from app.config import get_settings
from app.db.session import engine
from app.services.scheduler_service import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().scheduler_enabled:
        start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(sources.router)
app.include_router(articles.router)
app.include_router(ingestion.router)
app.include_router(daily_reading.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
