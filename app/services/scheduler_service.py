import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.ingestion_service import ingest_all_enabled_sources
from app.agent.runner import execute_agent_run
from app.services.reading_list_service import local_today
from app.services.run_service import create_agent_run

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=get_settings().scheduler_timezone)


def _scheduled_ingestion() -> None:
    try:
        with SessionLocal() as session:
            ingest_all_enabled_sources(session)
    except Exception:
        logger.exception("Scheduled RSS ingestion failed")


def _scheduled_daily_list() -> None:
    try:
        run_ids: list[int] = []
        with SessionLocal() as session:
            user_ids = list(
                session.scalars(select(User.id).where(User.is_active.is_(True)))
            )
            for user_id in user_ids:
                run = create_agent_run(
                    session,
                    user_id=user_id,
                    list_date=local_today(),
                    max_expansion_rounds=get_settings().agent_max_expansion_rounds,
                )
                run_ids.append(run.id)
        for run_id in run_ids:
            execute_agent_run(run_id, regenerate=True)
    except Exception:
        logger.exception("Scheduled daily reading list generation failed")


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
    scheduler.add_job(
        _scheduled_daily_list,
        "cron",
        hour=settings.daily_list_hour,
        minute=0,
        id="daily-reading-list",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
