import json
import inspect
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy.orm import Session

from app.agent.routing import route_after_select
from app.agent.state import DailyRunState
from app.config import Settings, get_settings
from app.db.models import RunEventStatus
from app.db.session import SessionLocal
from app.nodes.classify import classify_node
from app.nodes.ai_classify import ai_classify_node
from app.nodes.apply_evidence import apply_evidence_node
from app.nodes.chunk_articles import chunk_articles_node
from app.nodes.collect import collect_node
from app.nodes.content_deduplicate import content_deduplicate_node
from app.nodes.compare_evidence import compare_evidence_node
from app.nodes.cluster_stories import cluster_stories_node
from app.nodes.embed_articles import embed_articles_node
from app.nodes.embed_chunks import embed_chunks_node
from app.nodes.exact_deduplicate import exact_deduplicate_node
from app.nodes.expand_sources import expand_sources_node
from app.nodes.extract import extract_node
from app.nodes.extract_claims import extract_claims_node
from app.nodes.filter import filter_node
from app.nodes.finalize import finalize_node
from app.nodes.load_settings import load_settings_node
from app.nodes.personalize import personalize_node
from app.nodes.persist_list import persist_list_node
from app.nodes.select import select_node
from app.nodes.supplement import supplement_node
from app.services.run_service import (
    elapsed_milliseconds,
    fail_run,
    finish_run_event,
    start_run_event,
    update_run_progress,
)

logger = logging.getLogger("daily_reading.agent.graph")
NodeResult = dict[str, object]
NodeHandler = Callable[
    [DailyRunState, Session, Settings], NodeResult | Awaitable[NodeResult]
]

DEFAULT_HANDLERS: dict[str, NodeHandler] = {
    "load_settings": load_settings_node,
    "collect": collect_node,
    "exact_deduplicate": exact_deduplicate_node,
    "extract": extract_node,
    "content_deduplicate": content_deduplicate_node,
    "classify": classify_node,
    "filter": filter_node,
    "ai_classify": ai_classify_node,
    "embed_articles": embed_articles_node,
    "cluster_stories": cluster_stories_node,
    "chunk_articles": chunk_articles_node,
    "embed_chunks": embed_chunks_node,
    "extract_claims": extract_claims_node,
    "compare_evidence": compare_evidence_node,
    "apply_evidence": apply_evidence_node,
    "personalize": personalize_node,
    "select": select_node,
    "expand_sources": expand_sources_node,
    "persist_list": persist_list_node,
    "supplement": supplement_node,
    "finalize": finalize_node,
}


def _event_message(updates: dict[str, object]) -> str | None:
    stats = updates.get("stats")
    if not isinstance(stats, dict):
        return None
    return json.dumps(stats, sort_keys=True, default=str)[:4000]


def tracked_node(
    name: str,
    handler: NodeHandler,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    settings_provider: Callable[[], Settings] = get_settings,
) -> Callable[[DailyRunState], NodeResult | Awaitable[NodeResult]]:
    def finish_success(
        state: DailyRunState,
        session: Session,
        event_id: int,
        started: float,
        updates: NodeResult,
    ) -> NodeResult:
        name_for_log = name
        run_id = state["run_id"]
        merged = {**state, **updates}
        elapsed_ms = elapsed_milliseconds(started)
        finish_run_event(
            session,
            event_id,
            status=RunEventStatus.COMPLETE,
            elapsed_ms=elapsed_ms,
            message=_event_message(updates),
        )
        update_run_progress(
            session,
            run_id,
            node_name=name_for_log,
            expansion_round=int(merged.get("expansion_round", 0)),
            selected_count=len(merged.get("selected_article_ids", [])),
            reading_list_id=merged.get("reading_list_id"),
            complete=name_for_log == "finalize",
        )
        logger.info(
            "timing stage=agent.%s status=ok elapsed_ms=%.2f run_id=%s",
            name_for_log,
            elapsed_ms,
            run_id,
        )
        return updates

    def finish_failure(
        state: DailyRunState,
        session: Session,
        event_id: int,
        started: float,
        exc: Exception,
    ) -> None:
        session.rollback()
        elapsed_ms = elapsed_milliseconds(started)
        with session_factory() as error_session:
            finish_run_event(
                error_session,
                event_id,
                status=RunEventStatus.FAILED,
                elapsed_ms=elapsed_ms,
                message=str(exc)[:4000],
            )
        fail_run(state["run_id"], name, exc)

    if inspect.iscoroutinefunction(handler):
        async def execute_async(state: DailyRunState) -> NodeResult:
            started = perf_counter()
            run_id = state["run_id"]
            with session_factory() as session:
                event = start_run_event(session, run_id, name)
                try:
                    updates = await handler(state, session, settings_provider())
                    return finish_success(
                        state, session, event.id, started, updates
                    )
                except Exception as exc:
                    finish_failure(state, session, event.id, started, exc)
                    raise

        execute_async.__name__ = name
        return execute_async

    def execute(state: DailyRunState) -> NodeResult:
        started = perf_counter()
        run_id = state["run_id"]
        with session_factory() as session:
            event = start_run_event(session, run_id, name)
            try:
                updates = handler(state, session, settings_provider())
                if inspect.isawaitable(updates):
                    raise TypeError(f"Node {name} unexpectedly returned an awaitable")
                return finish_success(state, session, event.id, started, updates)
            except Exception as exc:
                finish_failure(state, session, event.id, started, exc)
                raise

    execute.__name__ = name
    return execute


def build_daily_run_graph(
    *,
    checkpointer: Any | None = None,
    handlers: dict[str, NodeHandler] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    settings_provider: Callable[[], Settings] = get_settings,
    track_events: bool = True,
):
    selected_handlers = handlers or DEFAULT_HANDLERS
    builder = StateGraph(DailyRunState)
    retry_policy = RetryPolicy(max_attempts=3, initial_interval=1.0)
    for name, handler in selected_handlers.items():
        if track_events:
            node = tracked_node(
                name,
                handler,
                session_factory=session_factory,
                settings_provider=settings_provider,
            )
        else:
            if inspect.iscoroutinefunction(handler):
                async def async_node(
                    state: DailyRunState,
                    selected_handler: NodeHandler = handler,
                ) -> NodeResult:
                    result = selected_handler(
                        state, None, settings_provider()  # type: ignore[arg-type]
                    )
                    if not inspect.isawaitable(result):
                        raise TypeError("Async node handler returned a non-awaitable")
                    return await result

                async_node.__name__ = name
                node = async_node
            else:
                def sync_node(
                    state: DailyRunState,
                    selected_handler: NodeHandler = handler,
                ) -> NodeResult:
                    result = selected_handler(
                        state, None, settings_provider()  # type: ignore[arg-type]
                    )
                    if inspect.isawaitable(result):
                        raise TypeError("Sync node handler returned an awaitable")
                    return result

                sync_node.__name__ = name
                node = sync_node
        if name in {
            "collect",
            "extract",
            "ai_classify",
            "embed_articles",
            "embed_chunks",
            "extract_claims",
            "compare_evidence",
            "supplement",
        }:
            builder.add_node(name, node, retry_policy=retry_policy)
        else:
            builder.add_node(name, node)

    builder.add_edge(START, "load_settings")
    builder.add_edge("load_settings", "collect")
    builder.add_edge("collect", "exact_deduplicate")
    builder.add_edge("exact_deduplicate", "extract")
    builder.add_edge("extract", "content_deduplicate")
    builder.add_edge("content_deduplicate", "classify")
    builder.add_edge("classify", "filter")
    builder.add_edge("filter", "ai_classify")
    builder.add_edge("ai_classify", "embed_articles")
    builder.add_edge("embed_articles", "cluster_stories")
    builder.add_edge("cluster_stories", "chunk_articles")
    builder.add_edge("chunk_articles", "embed_chunks")
    builder.add_edge("embed_chunks", "extract_claims")
    builder.add_edge("extract_claims", "compare_evidence")
    builder.add_edge("compare_evidence", "apply_evidence")
    builder.add_edge("apply_evidence", "personalize")
    builder.add_edge("personalize", "select")
    builder.add_conditional_edges(
        "select",
        route_after_select,
        {"finalize": "persist_list", "expand_sources": "expand_sources"},
    )
    builder.add_edge("expand_sources", "classify")
    builder.add_edge("persist_list", "supplement")
    builder.add_edge("supplement", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
