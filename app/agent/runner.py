import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import text

from app.agent.graph import build_daily_run_graph
from app.agent.state import DailyRunState
from app.config import get_settings
from app.db.models import DailyRun
from app.db.session import SessionLocal, engine

logger = logging.getLogger("daily_reading.agent.runner")


def _checkpoint_database_url() -> str:
    url = get_settings().resolved_database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    # Docker publishes PostgreSQL on IPv4. Some Windows installations resolve
    # localhost to ::1 first and wait for a long timeout before trying 127.0.0.1.
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}connect_timeout=10"


@contextmanager
def postgres_checkpointer() -> Iterator[PostgresSaver]:
    with PostgresSaver.from_conn_string(_checkpoint_database_url()) as saver:
        saver.setup()
        yield saver


@contextmanager
def claim_run(run_id: int) -> Iterator[None]:
    """Prevent two workers from executing the same run concurrently."""
    with engine.connect() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:run_id)"), {"run_id": run_id}
        )
        if not acquired:
            raise RuntimeError(f"Agent run {run_id} is already being executed")
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:run_id)"), {"run_id": run_id}
            )
            connection.commit()


def initial_run_state(run: DailyRun, *, regenerate: bool) -> DailyRunState:
    return DailyRunState(
        run_id=run.id,
        thread_id=run.thread_id,
        user_id=run.user_id,
        list_date=run.list_date.isoformat(),
        regenerate=regenerate,
        expansion_round=run.expansion_round,
        max_expansion_rounds=run.max_expansion_rounds,
        candidate_article_ids=[],
        eligible_article_ids=[],
        selected_article_ids=[],
        story_cluster_ids=[],
        evidence_cluster_ids=[],
        candidate_scores=[],
        selected_scores=[],
        stats={},
        errors=[],
        status="queued",
    )


def _config(thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": get_settings().agent_recursion_limit,
    }


def execute_agent_run(run_id: int, *, regenerate: bool = True) -> DailyRunState:
    with SessionLocal() as session:
        run = session.get(DailyRun, run_id)
        if run is None:
            raise LookupError(f"Agent run {run_id} does not exist")
        state = initial_run_state(run, regenerate=regenerate)
        thread_id = run.thread_id
    with claim_run(run_id), postgres_checkpointer() as saver:
        graph = build_daily_run_graph(checkpointer=saver)
        return graph.invoke(state, _config(thread_id))


def resume_agent_run(run_id: int) -> DailyRunState:
    with SessionLocal() as session:
        run = session.get(DailyRun, run_id)
        if run is None:
            raise LookupError(f"Agent run {run_id} does not exist")
        thread_id = run.thread_id
    with claim_run(run_id), postgres_checkpointer() as saver:
        graph = build_daily_run_graph(checkpointer=saver)
        snapshot = graph.get_state(_config(thread_id))
        if not snapshot.values:
            raise LookupError(f"Agent run {run_id} has no checkpoint to resume")
        return graph.invoke(None, _config(thread_id))
