import logging
from datetime import UTC, date, datetime
from time import perf_counter
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    AgentRunStatus,
    DailyRun,
    RunEvent,
    RunEventStatus,
    User,
)

logger = logging.getLogger("daily_reading.agent")


def create_agent_run(
    session: Session,
    *,
    user_id: int,
    list_date: date,
    max_expansion_rounds: int,
) -> DailyRun:
    if session.get(User, user_id) is None:
        raise LookupError(f"User {user_id} does not exist")
    run = DailyRun(
        thread_id=str(uuid4()),
        user_id=user_id,
        list_date=list_date,
        status=AgentRunStatus.QUEUED.value,
        expansion_round=0,
        max_expansion_rounds=max_expansion_rounds,
        selected_count=0,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_agent_run(session: Session, run_id: int) -> DailyRun | None:
    return session.scalar(
        select(DailyRun)
        .where(DailyRun.id == run_id)
        .options(selectinload(DailyRun.events))
    )


def list_agent_runs(
    session: Session, user_id: int, *, limit: int = 50
) -> list[DailyRun]:
    return list(
        session.scalars(
            select(DailyRun)
            .where(DailyRun.user_id == user_id)
            .order_by(DailyRun.created_at.desc())
            .limit(limit)
        )
    )


def start_run_event(session: Session, run_id: int, node_name: str) -> RunEvent:
    attempt = session.scalar(
        select(func.coalesce(func.max(RunEvent.attempt), 0) + 1).where(
            RunEvent.run_id == run_id,
            RunEvent.node_name == node_name,
        )
    )
    event = RunEvent(
        run_id=run_id,
        node_name=node_name,
        attempt=int(attempt or 1),
        status=RunEventStatus.RUNNING.value,
        started_at=datetime.now(UTC),
    )
    run = session.get(DailyRun, run_id)
    if run is None:
        raise LookupError(f"Agent run {run_id} does not exist")
    run.status = AgentRunStatus.RUNNING.value
    run.current_node = node_name
    run.last_error = None
    if run.started_at is None:
        run.started_at = datetime.now(UTC)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def finish_run_event(
    session: Session,
    event_id: int,
    *,
    status: RunEventStatus,
    elapsed_ms: float,
    message: str | None = None,
) -> None:
    event = session.get(RunEvent, event_id)
    if event is None:
        return
    event.status = status.value
    event.elapsed_ms = round(elapsed_ms, 2)
    event.message = message
    event.completed_at = datetime.now(UTC)
    session.commit()


def update_run_progress(
    session: Session,
    run_id: int,
    *,
    node_name: str,
    expansion_round: int,
    selected_count: int,
    reading_list_id: int | None = None,
    complete: bool = False,
) -> None:
    run = session.get(DailyRun, run_id)
    if run is None:
        return
    run.current_node = node_name
    run.expansion_round = expansion_round
    run.selected_count = selected_count
    if reading_list_id is not None:
        run.reading_list_id = reading_list_id
    if complete:
        run.status = AgentRunStatus.COMPLETE.value
        run.completed_at = datetime.now(UTC)
    else:
        run.status = AgentRunStatus.RUNNING.value
    session.commit()


def fail_run(run_id: int, node_name: str, error: Exception) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        run = session.get(DailyRun, run_id)
        if run is None:
            return
        run.status = AgentRunStatus.FAILED.value
        run.current_node = node_name
        run.last_error = str(error)[:4000]
        session.commit()
    logger.exception("agent run failed run_id=%s node=%s", run_id, node_name)


def elapsed_milliseconds(started: float) -> float:
    return (perf_counter() - started) * 1000
