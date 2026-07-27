from collections import Counter
from typing import cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import NodeHandler, build_daily_run_graph
from app.agent.routing import route_after_select
from app.agent.state import CandidateScore, DailyRunState
from app.config import Settings
from app.services.agent_stage_service import select_scored_articles


def _handler(
    updates: dict[str, object] | None = None,
    *,
    calls: Counter[str] | None = None,
    name: str = "node",
) -> NodeHandler:
    def execute(state, _session, _settings):
        if calls is not None:
            calls[name] += 1
        return dict(updates or {})

    return execute


def _handlers(calls: Counter[str], fail_classify_once: bool = False):
    classify_attempts = 0

    def load(state, _session, _settings):
        calls["load_settings"] += 1
        return {
            "target_article_count": 1,
            "target_reading_minutes": 30,
            "max_expansion_rounds": 1,
            "expansion_round": state.get("expansion_round", 0),
        }

    def classify(state, _session, _settings):
        nonlocal classify_attempts
        calls["classify"] += 1
        classify_attempts += 1
        if fail_classify_once and classify_attempts == 1:
            raise RuntimeError("temporary classification failure")
        return {}

    def select(state, _session, _settings):
        calls["select"] += 1
        return {
            "selected_article_ids": [10],
            "selected_scores": [],
        }

    handlers = {
        name: _handler(calls=calls, name=name)
        for name in (
            "collect",
            "exact_deduplicate",
            "extract",
            "content_deduplicate",
            "filter",
            "ai_classify",
            "embed_articles",
            "cluster_stories",
            "chunk_articles",
            "embed_chunks",
            "extract_claims",
            "compare_evidence",
            "apply_evidence",
            "personalize",
            "expand_sources",
            "finalize",
        )
    }
    handlers.update(
        {"load_settings": load, "classify": classify, "select": select}
    )
    return cast(dict[str, NodeHandler], handlers)


def test_route_stops_at_target_or_max_rounds() -> None:
    assert route_after_select(
        DailyRunState(
            selected_article_ids=[1], target_article_count=1, expansion_round=0
        )
    ) == "finalize"
    assert route_after_select(
        DailyRunState(
            selected_article_ids=[],
            target_article_count=1,
            expansion_round=3,
            max_expansion_rounds=3,
        )
    ) == "finalize"
    assert route_after_select(
        DailyRunState(
            selected_article_ids=[],
            target_article_count=1,
            expansion_round=0,
            max_expansion_rounds=3,
        )
    ) == "expand_sources"


def test_selection_honors_count_and_reading_budget() -> None:
    scores = [
        CandidateScore(
            article_id=1,
            total_score=10,
            base_score=10,
            personalization_score=0,
            freshness_score=0,
            topic_score=0,
            source_score=0,
            length_score=0,
            reading_minutes=8,
            selection_reason="first",
        ),
        CandidateScore(
            article_id=2,
            total_score=9,
            base_score=9,
            personalization_score=0,
            freshness_score=0,
            topic_score=0,
            source_score=0,
            length_score=0,
            reading_minutes=4,
            selection_reason="second",
        ),
    ]
    selected = select_scored_articles(scores, target_count=2, target_minutes=10)
    assert [item["article_id"] for item in selected] == [1]


def test_checkpoint_resume_does_not_repeat_completed_nodes() -> None:
    calls: Counter[str] = Counter()
    checkpointer = InMemorySaver()
    graph = build_daily_run_graph(
        checkpointer=checkpointer,
        handlers=_handlers(calls, fail_classify_once=True),
        settings_provider=lambda: Settings(_env_file=None),
        track_events=False,
    )
    config = {"configurable": {"thread_id": "resume-test"}}
    state = DailyRunState(
        run_id=1,
        thread_id="resume-test",
        user_id=1,
        list_date="2026-07-26",
        expansion_round=0,
        selected_article_ids=[],
    )
    with pytest.raises(RuntimeError, match="temporary classification failure"):
        graph.invoke(state, config)

    assert calls["load_settings"] == 1
    assert calls["collect"] == 1
    result = graph.invoke(None, config)
    assert result["selected_article_ids"] == [10]
    assert calls["finalize"] == 1
    assert calls["load_settings"] == 1
    assert calls["collect"] == 1
    assert calls["classify"] == 2
    assert calls["ai_classify"] == 1
    assert calls["embed_articles"] == 1
    assert calls["compare_evidence"] == 1
