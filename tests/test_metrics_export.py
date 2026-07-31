import csv
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.export_run_metrics import (
    RunSnapshot,
    _base_metric_definitions,
    _event_stats,
    _llm_metric_definitions,
    _output_filenames,
    _write_llm_details,
    _write_step_details,
    _write_summary,
)


def test_output_suffix_preserves_existing_metrics_files() -> None:
    assert _output_filenames(None) == (
        "run_metrics_summary.csv",
        "llm_calls_detail.csv",
        "run_step_metrics.csv",
    )
    assert _output_filenames("2") == (
        "run_metrics_summary_2.csv",
        "llm_calls_detail_2.csv",
        "run_step_metrics_2.csv",
    )


def _snapshot(run_id: int, *, node_seconds: float, response_seconds: float) -> RunSnapshot:
    started = datetime(2026, 7, 30, tzinfo=UTC)
    run = SimpleNamespace(
        id=run_id,
        status="complete",
        started_at=started,
        completed_at=started + timedelta(seconds=node_seconds + 2),
        expansion_round=0,
        selected_count=5,
    )
    events = (
        SimpleNamespace(
            id=1,
            node_name="embed_articles",
            elapsed_ms=node_seconds * 1000,
            message='{"articles_embedded": 10, "selected_candidates": 5}',
        ),
    )
    calls = (
        SimpleNamespace(
            id=run_id,
            role="article_embedding",
            provider="qwen",
            model="embedding-model",
            status="complete",
            elapsed_ms=response_seconds * 1000,
            input_tokens=100,
            output_tokens=None,
            created_at=started,
            error=None,
        ),
    )
    return RunSnapshot(
        run=run,
        events=events,
        model_calls=calls,
        stats=_event_stats(events),
        node_seconds={"embed_articles": node_seconds},
        node_attempts={"embed_articles": 1},
    )


def test_summary_has_three_run_values_and_average(tmp_path):
    snapshots = [
        _snapshot(1, node_seconds=10, response_seconds=4),
        _snapshot(2, node_seconds=20, response_seconds=5),
        _snapshot(3, node_seconds=30, response_seconds=6),
    ]
    output = tmp_path / "summary.csv"
    definitions = [
        *_base_metric_definitions(),
        *_llm_metric_definitions(["article_embedding"]),
    ]

    _write_summary(output, snapshots, definitions)

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["metric"]: row for row in csv.DictReader(handle)}
    node = rows["node.embed_articles.seconds"]
    assert node["run_1"] == "10"
    assert node["run_2"] == "20"
    assert node["run_3"] == "30"
    assert node["average"] == "20.000"
    assert rows["workload.article_embeddings_created"]["run_1"] == "10"
    assert rows["llm.article_embedding.average_response_seconds"]["average"] == "5.000"


def test_llm_detail_is_per_response_without_article_timing(tmp_path):
    output = tmp_path / "calls.csv"
    _write_llm_details(
        output,
        [_snapshot(7, node_seconds=9, response_seconds=3.25)],
    )

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["run_id"] == "7"
    assert rows[0]["response_seconds"] == "3.250"
    assert "article_id" not in rows[0]


def test_step_detail_pairs_time_and_volume_for_every_node(tmp_path):
    output = tmp_path / "steps.csv"
    _write_step_details(
        output,
        [_snapshot(7, node_seconds=9, response_seconds=3.25)],
    )

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["step"]: row for row in csv.DictReader(handle)}
    embedded = rows["embed_articles"]
    assert embedded["seconds"] == "9"
    assert embedded["volume"] == "10"
    assert embedded["volume_unit"] == "embeddings"
    assert "extract" in rows
