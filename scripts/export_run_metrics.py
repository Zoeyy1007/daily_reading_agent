"""Export aggregate timing and workload metrics for Daily Reading agent runs.

This exporter deliberately reports batch-level processing time. It never emits
per-article extraction or processing durations.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models import DailyRun, ModelCall, RunEvent  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


NODE_ORDER = (
    "load_settings",
    "collect",
    "exact_deduplicate",
    "extract",
    "content_deduplicate",
    "classify",
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
    "select",
    "expand_sources",
    "persist_list",
    "supplement",
    "finalize",
)

KNOWN_LLM_ROLES = (
    "classification",
    "article_embedding",
    "chunk_embedding",
    "claim_extraction",
    "claim_embedding",
    "evidence_comparison",
    "supplement_planning",
    "supplement_composition",
    "supplement_verification",
)


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run: DailyRun
    events: tuple[RunEvent, ...]
    model_calls: tuple[ModelCall, ...]
    stats: dict[str, object]
    node_seconds: dict[str, float]
    node_attempts: dict[str, int]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    unit: str
    description: str
    value: Callable[[RunSnapshot], object | None]


def _event_stats(events: tuple[RunEvent, ...]) -> dict[str, object]:
    """Merge the cumulative JSON stats saved by successful node events."""
    stats: dict[str, object] = {}
    for event in sorted(events, key=lambda item: item.id):
        if not event.message:
            continue
        try:
            payload = json.loads(event.message)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            stats.update(payload)
    return stats


def _snapshot(session: Session, run_id: int) -> RunSnapshot:
    run = session.scalar(
        select(DailyRun)
        .where(DailyRun.id == run_id)
        .options(selectinload(DailyRun.events))
    )
    if run is None:
        raise LookupError(f"Agent run {run_id} does not exist")
    events = tuple(sorted(run.events, key=lambda item: item.id))
    calls = tuple(
        session.scalars(
            select(ModelCall)
            .where(ModelCall.run_id == run_id)
            .order_by(ModelCall.created_at, ModelCall.id)
        )
    )
    node_milliseconds: dict[str, float] = defaultdict(float)
    node_attempts: dict[str, int] = defaultdict(int)
    for event in events:
        node_attempts[event.node_name] += 1
        if event.elapsed_ms is not None:
            node_milliseconds[event.node_name] += float(event.elapsed_ms)
    return RunSnapshot(
        run=run,
        events=events,
        model_calls=calls,
        stats=_event_stats(events),
        node_seconds={name: value / 1000.0 for name, value in node_milliseconds.items()},
        node_attempts=dict(node_attempts),
    )


def _stat(name: str, *, default: object | None = None) -> Callable[[RunSnapshot], object | None]:
    return lambda snapshot: snapshot.stats.get(name, default)


def _sum_stats(*names: str) -> Callable[[RunSnapshot], int]:
    def value(snapshot: RunSnapshot) -> int:
        return sum(
            int(snapshot.stats.get(name, 0))
            for name in names
            if isinstance(snapshot.stats.get(name, 0), int | float)
        )

    return value


def _node_seconds(name: str) -> Callable[[RunSnapshot], float | None]:
    return lambda snapshot: snapshot.node_seconds.get(name)


def _node_attempts(name: str) -> Callable[[RunSnapshot], int]:
    return lambda snapshot: snapshot.node_attempts.get(name, 0)


def _wall_seconds(snapshot: RunSnapshot) -> float | None:
    if snapshot.run.started_at is None or snapshot.run.completed_at is None:
        return None
    return (snapshot.run.completed_at - snapshot.run.started_at).total_seconds()


def _supplement_items(snapshot: RunSnapshot) -> int:
    return sum(
        int(snapshot.stats.get(name, 0))
        for name in (
            "supplements_complete",
            "supplements_skipped",
            "supplements_insufficient",
            "supplements_failed",
        )
        if isinstance(snapshot.stats.get(name, 0), int | float)
    )


def _node_volume_definitions() -> dict[
    str, tuple[Callable[[RunSnapshot], object | None], str, str]
]:
    return {
        "load_settings": (
            lambda snapshot: 1 if snapshot.node_attempts.get("load_settings") else 0,
            "users",
            "User preference records loaded.",
        ),
        "collect": (_stat("sources_polled", default=0), "sources", "RSS sources polled."),
        "exact_deduplicate": (
            _stat("exact_unique_candidates", default=0),
            "articles",
            "New candidate articles retained after URL/GUID deduplication.",
        ),
        "extract": (
            _sum_stats("extracted", "extraction_failed"),
            "articles",
            "Articles submitted to full-text extraction.",
        ),
        "content_deduplicate": (
            _sum_stats("content_unique_candidates", "content_duplicates"),
            "articles",
            "Articles checked for duplicate extracted content.",
        ),
        "classify": (
            _stat("classified_candidates", default=0),
            "articles",
            "Articles processed by local classification.",
        ),
        "filter": (
            _stat("classified_candidates", default=0),
            "articles",
            "Classified articles checked against hard filters.",
        ),
        "ai_classify": (
            _stat("ai_classified", default=0),
            "articles",
            "Articles newly classified by the LLM.",
        ),
        "embed_articles": (
            _stat("articles_embedded", default=0),
            "embeddings",
            "Article embeddings created.",
        ),
        "cluster_stories": (
            _stat("eligible_candidates", default=0),
            "articles",
            "Eligible articles considered for story clustering.",
        ),
        "chunk_articles": (
            _stat("chunks_created", default=0),
            "chunks",
            "Article chunks created.",
        ),
        "embed_chunks": (
            _stat("chunks_embedded", default=0),
            "embeddings",
            "Chunk embeddings created.",
        ),
        "extract_claims": (
            _stat("claims_created", default=0),
            "claims",
            "Grounded claims created.",
        ),
        "compare_evidence": (
            _stat("clusters_compared", default=0),
            "clusters",
            "Story clusters compared for evidence differences.",
        ),
        "apply_evidence": (
            _stat("post_evidence_candidates", default=0),
            "articles",
            "Representative candidates retained after evidence comparison.",
        ),
        "personalize": (
            _stat("scored_candidates", default=0),
            "articles",
            "Candidate articles scored and personalized.",
        ),
        "select": (
            _stat("scored_candidates", default=0),
            "articles",
            "Scored candidates considered under count and time budgets.",
        ),
        "expand_sources": (
            _stat("round_1_database_candidates", default=0),
            "articles",
            "Database candidates added by the currently implemented expansion tool.",
        ),
        "persist_list": (
            _stat("final_article_count", default=0),
            "articles",
            "Selected articles written to the daily list.",
        ),
        "supplement": (
            _supplement_items,
            "items",
            "Reading-list items evaluated for supplements.",
        ),
        "finalize": (
            lambda snapshot: snapshot.run.selected_count,
            "articles",
            "Selected articles finalized for the completed run.",
        ),
    }


def _base_metric_definitions() -> list[MetricDefinition]:
    definitions = [
        MetricDefinition("run.status", "text", "Final DailyRun status.", lambda s: s.run.status),
        MetricDefinition(
            "run.wall_clock_seconds",
            "seconds",
            "Wall-clock time from the first node starting until the run completes; includes retry waits.",
            _wall_seconds,
        ),
        MetricDefinition(
            "run.expansion_rounds",
            "count",
            "Number of source-expansion rounds reached.",
            lambda s: s.run.expansion_round,
        ),
        MetricDefinition(
            "run.selected_articles",
            "articles",
            "Number of articles selected into the final list.",
            lambda s: s.run.selected_count,
        ),
        MetricDefinition(
            "run.llm_api_responses",
            "responses",
            "Total recorded model API calls, including embeddings.",
            lambda s: len(s.model_calls),
        ),
    ]

    count_metrics = (
        ("workload.sources_polled", "sources", "sources_polled", "Enabled RSS sources polled."),
        ("workload.articles_discovered", "articles", "discovered", "New RSS article rows discovered."),
        ("workload.exact_duplicates", "articles", "exact_duplicates", "URL/GUID duplicates skipped."),
        ("workload.articles_extracted", "articles", "extracted", "Articles successfully extracted."),
        ("workload.article_extraction_failures", "articles", "extraction_failed", "Articles that failed full-text extraction."),
        ("workload.content_unique_articles", "articles", "content_unique_candidates", "Candidates remaining after content-hash deduplication."),
        ("workload.classified_articles", "articles", "classified_candidates", "Articles processed by local language/content classification."),
        ("workload.eligible_articles", "articles", "eligible_candidates", "Articles accepted by hard filters."),
        ("workload.ai_classified_articles", "articles", "ai_classified", "Articles newly classified by the configured LLM."),
        ("workload.article_embeddings_created", "embeddings", "articles_embedded", "Article embeddings newly created."),
        ("workload.story_clusters", "clusters", "story_clusters", "Story clusters touched by the run."),
        ("workload.evidence_clusters", "clusters", "evidence_clusters", "Multi-publisher clusters eligible for evidence work."),
        ("workload.article_chunks_created", "chunks", "chunks_created", "Article chunks newly created."),
        ("workload.chunk_embeddings_created", "embeddings", "chunks_embedded", "Chunk embeddings newly created."),
        ("workload.claims_created", "claims", "claims_created", "Grounded article claims newly created."),
        ("workload.clusters_compared", "clusters", "clusters_compared", "Clusters sent through evidence comparison."),
        ("workload.post_evidence_candidates", "articles", "post_evidence_candidates", "Articles remaining after representative selection."),
        ("workload.scored_articles", "articles", "scored_candidates", "Articles scored for ranking/personalization."),
        ("workload.selected_articles", "articles", "selected_candidates", "Articles selected under count/time budgets."),
        ("workload.supplement_evidence_items", "items", "supplement_evidence_items", "Supplement evidence excerpts persisted."),
        ("workload.supplement_cards", "cards", "supplement_cards", "Verified supplement cards persisted."),
    )
    definitions.extend(
        MetricDefinition(metric, unit, description, _stat(stat_name, default=0))
        for metric, unit, stat_name, description in count_metrics
    )

    batch_metrics = (
        ("rss_collection", "collect", _stat("sources_polled", default=0), "sources", "RSS sources processed as one run-level batch."),
        ("article_extraction", "extract", _sum_stats("extracted", "extraction_failed"), "articles", "Articles extracted or failed as one batch; no per-article timing."),
        ("local_classification", "classify", _stat("classified_candidates", default=0), "articles", "Articles locally classified as one batch."),
        ("ai_classification", "ai_classify", _stat("ai_classified", default=0), "articles", "Articles newly sent to LLM classification."),
        ("article_embedding", "embed_articles", _stat("articles_embedded", default=0), "embeddings", "Article embeddings created during the node."),
        ("story_clustering", "cluster_stories", _stat("eligible_candidates", default=0), "articles", "Eligible articles considered for clustering."),
        ("chunk_creation", "chunk_articles", _stat("chunks_created", default=0), "chunks", "Chunks created during the node."),
        ("chunk_embedding", "embed_chunks", _stat("chunks_embedded", default=0), "embeddings", "Chunk embeddings created during the node."),
        ("claim_extraction", "extract_claims", _stat("claims_created", default=0), "claims", "Claims created during retrieval, LLM extraction, and claim embedding."),
        ("evidence_comparison", "compare_evidence", _stat("clusters_compared", default=0), "clusters", "Clusters compared during the evidence node."),
        ("personalization", "personalize", _stat("scored_candidates", default=0), "articles", "Articles scored and personalized."),
        ("supplement_generation", "supplement", _supplement_items, "items", "Reading-list items processed for supplements."),
    )
    for label, node, count_value, count_unit, description in batch_metrics:
        definitions.append(
            MetricDefinition(
                f"batch.{label}.processed",
                count_unit,
                description,
                count_value,
            )
        )
        definitions.append(
            MetricDefinition(
                f"batch.{label}.seconds",
                "seconds",
                f"Total {node} node time across all attempts.",
                _node_seconds(node),
            )
        )

    node_volumes = _node_volume_definitions()
    for node in NODE_ORDER:
        volume_value, volume_unit, volume_description = node_volumes[node]
        definitions.extend(
            (
                MetricDefinition(
                    f"node.{node}.seconds",
                    "seconds",
                    "Total elapsed node execution time across all attempts; excludes retry sleep.",
                    _node_seconds(node),
                ),
                MetricDefinition(
                    f"node.{node}.volume",
                    volume_unit,
                    volume_description,
                    volume_value,
                ),
                MetricDefinition(
                    f"node.{node}.attempts",
                    "attempts",
                    "Number of RunEvent attempts recorded for this node.",
                    _node_attempts(node),
                ),
            )
        )
    return definitions


def _calls_for_role(snapshot: RunSnapshot, role: str) -> list[ModelCall]:
    return [call for call in snapshot.model_calls if call.role == role]


def _llm_metric_definitions(roles: list[str]) -> list[MetricDefinition]:
    definitions: list[MetricDefinition] = []
    for role in roles:
        def calls(snapshot: RunSnapshot, selected_role: str = role) -> list[ModelCall]:
            return _calls_for_role(snapshot, selected_role)

        def elapsed(snapshot: RunSnapshot, selected_role: str = role) -> list[float]:
            return [
                float(call.elapsed_ms) / 1000.0
                for call in _calls_for_role(snapshot, selected_role)
                if call.elapsed_ms is not None
            ]

        definitions.extend(
            (
                MetricDefinition(
                    f"llm.{role}.responses",
                    "responses",
                    "Number of model API responses recorded for this role.",
                    lambda snapshot, selected=calls: len(selected(snapshot)),
                ),
                MetricDefinition(
                    f"llm.{role}.total_response_seconds",
                    "seconds",
                    "Sum of provider response durations for this role.",
                    lambda snapshot, selected=elapsed: sum(selected(snapshot)),
                ),
                MetricDefinition(
                    f"llm.{role}.average_response_seconds",
                    "seconds/response",
                    "Mean duration of one provider response for this role.",
                    lambda snapshot, selected=elapsed: (
                        statistics.fmean(selected(snapshot)) if selected(snapshot) else None
                    ),
                ),
                MetricDefinition(
                    f"llm.{role}.input_tokens",
                    "tokens",
                    "Total provider-reported input tokens for this role.",
                    lambda snapshot, selected=calls: sum(
                        call.input_tokens or 0 for call in selected(snapshot)
                    ),
                ),
                MetricDefinition(
                    f"llm.{role}.output_tokens",
                    "tokens",
                    "Total provider-reported output tokens for this role.",
                    lambda snapshot, selected=calls: sum(
                        call.output_tokens or 0 for call in selected(snapshot)
                    ),
                ),
            )
        )
    return definitions


def _format_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _average(values: list[object | None]) -> str:
    numeric = [
        float(value)
        for value in values
        if isinstance(value, int | float) and not isinstance(value, bool)
    ]
    return f"{statistics.fmean(numeric):.3f}" if numeric else ""


def _write_summary(
    path: Path,
    snapshots: list[RunSnapshot],
    definitions: list[MetricDefinition],
) -> None:
    headers = ["metric", "unit", *[f"run_{item.run.id}" for item in snapshots], "average", "description"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for definition in definitions:
            values = [definition.value(snapshot) for snapshot in snapshots]
            writer.writerow(
                [
                    definition.name,
                    definition.unit,
                    *[_format_value(value) for value in values],
                    _average(values),
                    definition.description,
                ]
            )


def _write_llm_details(path: Path, snapshots: list[RunSnapshot]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "run_id",
                "model_call_id",
                "role",
                "provider",
                "model",
                "status",
                "response_seconds",
                "input_tokens",
                "output_tokens",
                "created_at",
                "error",
            )
        )
        for snapshot in snapshots:
            for call in snapshot.model_calls:
                writer.writerow(
                    (
                        snapshot.run.id,
                        call.id,
                        call.role,
                        call.provider,
                        call.model,
                        call.status,
                        _format_value(
                            float(call.elapsed_ms) / 1000.0
                            if call.elapsed_ms is not None
                            else None
                        ),
                        call.input_tokens if call.input_tokens is not None else "",
                        call.output_tokens if call.output_tokens is not None else "",
                        call.created_at.isoformat() if isinstance(call.created_at, datetime) else "",
                        call.error or "",
                    )
                )


def _write_step_details(path: Path, snapshots: list[RunSnapshot]) -> None:
    volume_definitions = _node_volume_definitions()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "run_id",
                "run_status",
                "step",
                "seconds",
                "attempts",
                "volume",
                "volume_unit",
                "volume_description",
            )
        )
        for snapshot in snapshots:
            for node in NODE_ORDER:
                volume_value, volume_unit, volume_description = volume_definitions[node]
                writer.writerow(
                    (
                        snapshot.run.id,
                        snapshot.run.status,
                        node,
                        _format_value(snapshot.node_seconds.get(node)),
                        snapshot.node_attempts.get(node, 0),
                        _format_value(volume_value(snapshot)),
                        volume_unit,
                        volume_description,
                    )
                )


def _latest_run_ids(session: Session, count: int) -> list[int]:
    rows = list(
        session.scalars(
            select(DailyRun.id)
            .where(DailyRun.status == "complete")
            .order_by(DailyRun.created_at.desc(), DailyRun.id.desc())
            .limit(count)
        )
    )
    return sorted(rows)


def _file_suffix(value: str) -> str:
    suffix = value.strip()
    if not suffix or any(
        not (character.isalnum() or character in {"-", "_"})
        for character in suffix
    ):
        raise argparse.ArgumentTypeError(
            "suffix must contain only letters, numbers, hyphens, or underscores"
        )
    return suffix


def _output_filenames(suffix: str | None) -> tuple[str, str, str]:
    marker = f"_{suffix}" if suffix else ""
    return (
        f"run_metrics_summary{marker}.csv",
        f"llm_calls_detail{marker}.csv",
        f"run_step_metrics{marker}.csv",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export aggregate node, batch, embedding, and LLM metrics for agent runs."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--run-ids",
        nargs="+",
        type=int,
        help="Explicit agent run IDs to compare, for example: --run-ids 12 13 14",
    )
    group.add_argument(
        "--latest",
        type=int,
        metavar="COUNT",
        help="Use the latest COUNT completed agent runs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "metrics" / "results",
        help=(
            "Directory for run_metrics_summary.csv, llm_calls_detail.csv, "
            "and run_step_metrics.csv."
        ),
    )
    parser.add_argument(
        "--suffix",
        type=_file_suffix,
        help=(
            "Append a suffix to all output filenames. For example, --suffix 2 "
            "writes run_metrics_summary_2.csv, llm_calls_detail_2.csv, and "
            "run_step_metrics_2.csv."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.latest is not None and args.latest < 1:
        raise SystemExit("--latest must be at least 1")

    print("Metrics export started.", flush=True)
    print("Connecting to PostgreSQL...", flush=True)
    try:
        with SessionLocal() as session:
            session.connection()
            print("Connected to PostgreSQL.", flush=True)
            if args.run_ids:
                run_ids = args.run_ids
                print(
                    "Using requested run IDs: "
                    + ", ".join(str(run_id) for run_id in run_ids),
                    flush=True,
                )
            else:
                print(
                    f"Finding the latest {args.latest} completed runs...",
                    flush=True,
                )
                run_ids = _latest_run_ids(session, args.latest)
            if not run_ids:
                raise SystemExit("No matching completed agent runs were found")

            snapshots: list[RunSnapshot] = []
            for position, run_id in enumerate(run_ids, start=1):
                print(
                    f"Loading run {run_id} ({position}/{len(run_ids)})...",
                    flush=True,
                )
                snapshot = _snapshot(session, run_id)
                snapshots.append(snapshot)
                print(
                    f"Loaded run {run_id}: status={snapshot.run.status}, "
                    f"events={len(snapshot.events)}, "
                    f"model_calls={len(snapshot.model_calls)}.",
                    flush=True,
                )
    except OperationalError as exc:
        print(
            "Could not connect to PostgreSQL. Start it with "
            "'docker compose up -d db' and try again.",
            file=sys.stderr,
            flush=True,
        )
        print(f"Database error: {exc.orig}", file=sys.stderr, flush=True)
        return 1

    observed_roles = {
        call.role for snapshot in snapshots for call in snapshot.model_calls
    }
    roles = [*KNOWN_LLM_ROLES]
    roles.extend(sorted(observed_roles - set(roles)))
    definitions = [*_base_metric_definitions(), *_llm_metric_definitions(roles)]

    output_dir = args.output_dir.resolve()
    print(f"Writing CSV files to {output_dir}...", flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_name, calls_name, steps_name = _output_filenames(args.suffix)
    summary_path = output_dir / summary_name
    calls_path = output_dir / calls_name
    steps_path = output_dir / steps_name
    _write_summary(summary_path, snapshots, definitions)
    print(f"Wrote {summary_path.name}.", flush=True)
    _write_llm_details(calls_path, snapshots)
    print(f"Wrote {calls_path.name}.", flush=True)
    _write_step_details(steps_path, snapshots)
    print(f"Wrote {steps_path.name}.", flush=True)
    print(f"Exported run IDs: {', '.join(str(run_id) for run_id in run_ids)}")
    print(f"Summary: {summary_path}")
    print(f"LLM calls: {calls_path}")
    print(f"Steps: {steps_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
