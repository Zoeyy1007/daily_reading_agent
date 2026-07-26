import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.db.session import SessionLocal
from app.services.ingestion_service import ingest_all_enabled_sources

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def _scheduled_ingestion() -> None:
    try:
        with SessionLocal() as session:
            ingest_all_enabled_sources(session)
    except Exception:
        logger.exception("Scheduled RSS ingestion failed")


def start_scheduler() -> None:
    if scheduler.running:
        return
    settings = get_settings()
    scheduler.add_job(
        _scheduled_ingestion,
        "interval",
        minutes=settings.rss_poll_minutes,
        id="rss-ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
