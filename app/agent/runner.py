import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
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


@asynccontextmanager
async def async_postgres_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(
        _checkpoint_database_url()
    ) as saver:
        await saver.setup()
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


async def execute_agent_run_async(
    run_id: int, *, regenerate: bool = True
) -> DailyRunState:
    def load() -> tuple[DailyRunState, str]:
        with SessionLocal() as session:
            run = session.get(DailyRun, run_id)
            if run is None:
                raise LookupError(f"Agent run {run_id} does not exist")
            return initial_run_state(run, regenerate=regenerate), run.thread_id

    state, thread_id = await asyncio.to_thread(load)
    with claim_run(run_id):
        async with async_postgres_checkpointer() as saver:
            graph = build_daily_run_graph(checkpointer=saver)
            return await graph.ainvoke(state, _config(thread_id))


async def resume_agent_run_async(run_id: int) -> DailyRunState:
    def load_thread_id() -> str:
        with SessionLocal() as session:
            run = session.get(DailyRun, run_id)
            if run is None:
                raise LookupError(f"Agent run {run_id} does not exist")
            return run.thread_id

    thread_id = await asyncio.to_thread(load_thread_id)
    with claim_run(run_id):
        async with async_postgres_checkpointer() as saver:
            graph = build_daily_run_graph(checkpointer=saver)
            snapshot = await graph.aget_state(_config(thread_id))
            if not snapshot.values:
                raise LookupError(f"Agent run {run_id} has no checkpoint to resume")
            return await graph.ainvoke(None, _config(thread_id))


def _run_coroutine(
    coroutine_factory: Callable[[], Coroutine[object, object, DailyRunState]],
) -> DailyRunState:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop_factory = asyncio.SelectorEventLoop if os.name == "nt" else None
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            return runner.run(coroutine_factory())
    raise RuntimeError(
        "A synchronous agent runner cannot be called from an active event loop; "
        "await execute_agent_run_async() or resume_agent_run_async() instead"
    )


def execute_agent_run(run_id: int, *, regenerate: bool = True) -> DailyRunState:
    return _run_coroutine(
        lambda: execute_agent_run_async(run_id, regenerate=regenerate)
    )


def resume_agent_run(run_id: int) -> DailyRunState:
    return _run_coroutine(lambda: resume_agent_run_async(run_id))
