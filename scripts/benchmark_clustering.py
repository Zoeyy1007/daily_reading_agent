"""Benchmark story clustering with labeled synthetic articles.

The script uses the configured embedding provider but never writes its fixture
articles to PostgreSQL.  Its online centroid assignment mirrors the production
clustering rule in ``phase_five_service.cluster_articles``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.client import OpenAICompatibleClient  # noqa: E402
from app.ai.direct_providers import QwenEmbeddingProvider  # noqa: E402
from app.config import get_settings  # noqa: E402


DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "clustering_benchmark_articles.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "metrics" / "results"
DEFAULT_SWEEP = (0.70, 0.75, 0.80, 0.82, 0.85, 0.88, 0.90, 0.92, 0.95)


@dataclass(frozen=True, slots=True)
class Assignment:
    cluster_id: int
    similarity: float


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def online_centroid_cluster(
    vectors: Sequence[Sequence[float]], threshold: float
) -> list[Assignment]:
    """Assign each vector to its nearest centroid when similarity meets threshold."""
    centroids: list[list[float]] = []
    counts: list[int] = []
    assignments: list[Assignment] = []
    for vector_values in vectors:
        vector = list(vector_values)
        similarities = [cosine_similarity(vector, centroid) for centroid in centroids]
        best_index = max(range(len(similarities)), key=similarities.__getitem__) if similarities else -1
        best_similarity = similarities[best_index] if best_index >= 0 else 1.0
        if best_index < 0 or best_similarity < threshold:
            centroids.append(vector)
            counts.append(1)
            assignments.append(Assignment(len(centroids), 1.0))
            continue

        old_count = counts[best_index]
        centroids[best_index] = [
            ((old_value * old_count) + new_value) / (old_count + 1)
            for old_value, new_value in zip(centroids[best_index], vector, strict=True)
        ]
        counts[best_index] += 1
        assignments.append(Assignment(best_index + 1, best_similarity))
    return assignments


def clustering_metrics(
    expected: Sequence[str], predicted: Sequence[int]
) -> dict[str, float | int]:
    true_positive = false_positive = false_negative = true_negative = 0
    for left in range(len(expected)):
        for right in range(left + 1, len(expected)):
            expected_same = expected[left] == expected[right]
            predicted_same = predicted[left] == predicted[right]
            if expected_same and predicted_same:
                true_positive += 1
            elif not expected_same and predicted_same:
                false_positive += 1
            elif expected_same:
                false_negative += 1
            else:
                true_negative += 1
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total_pairs = true_positive + false_positive + false_negative + true_negative
    accuracy = (true_positive + true_negative) / total_pairs if total_pairs else 1.0

    members: dict[int, Counter[str]] = defaultdict(Counter)
    for expected_label, predicted_label in zip(expected, predicted, strict=True):
        members[predicted_label][expected_label] += 1
    purity = sum(max(labels.values()) for labels in members.values()) / len(expected) if expected else 1.0
    return {
        "article_count": len(expected),
        "expected_cluster_count": len(set(expected)),
        "predicted_cluster_count": len(set(predicted)),
        "pairwise_true_positive": true_positive,
        "pairwise_false_positive": false_positive,
        "pairwise_false_negative": false_negative,
        "pairwise_true_negative": true_negative,
        "pairwise_precision": precision,
        "pairwise_recall": recall,
        "pairwise_f1": f1,
        "pairwise_accuracy": accuracy,
        "purity": purity,
    }


def _article_text(article: dict[str, str]) -> str:
    return (
        f"Title: {article['title']}\n"
        f"Summary: {article['summary']}\n"
        f"Article: {article['content']}"
    )


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _append_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _metric_row(
    expected: list[str], assignments: list[Assignment], threshold: float
) -> dict[str, object]:
    metrics = clustering_metrics(expected, [item.cluster_id for item in assignments])
    return {"similarity_threshold": threshold, **metrics}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--threshold", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    threshold = args.threshold if args.threshold is not None else settings.story_cluster_similarity_threshold
    articles: list[dict[str, str]] = json.loads(args.fixture.read_text(encoding="utf-8"))
    expected = [article["expected_cluster"] for article in articles]
    print(
        f"Loaded {len(articles)} articles across {len(set(expected))} expected clusters.",
        flush=True,
    )

    api_key = settings.dashscope_api_key.get_secret_value() if settings.dashscope_api_key else ""
    client = OpenAICompatibleClient(
        api_key=api_key,
        base_url=settings.qwen_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    provider = QwenEmbeddingProvider(
        client,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    vectors: list[list[float]] = []
    embedding_seconds = 0.0
    embedding_calls = 0
    benchmark_started = perf_counter()
    texts = [_article_text(article) for article in articles]
    for start in range(0, len(texts), settings.embedding_batch_size):
        batch = texts[start : start + settings.embedding_batch_size]
        number = embedding_calls + 1
        print(f"Embedding batch {number} ({len(batch)} articles)...", flush=True)
        result = provider.embed(batch)
        vectors.extend(result.vectors)
        embedding_seconds += result.elapsed_ms / 1000
        embedding_calls += 1

    assignments = online_centroid_cluster(vectors, threshold)
    benchmark_seconds = perf_counter() - benchmark_started
    metric_values = _metric_row(expected, assignments, threshold)
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    benchmark_run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    summary = {
        "benchmark_run_id": benchmark_run_id,
        "created_at_utc": created_at,
        "provider": provider.provider_name,
        "model": provider.model,
        "embedding_dimensions": provider.dimensions,
        "embedding_calls": embedding_calls,
        "embedding_seconds": round(embedding_seconds, 6),
        "benchmark_wall_seconds": round(benchmark_seconds, 6),
        **metric_values,
        "ground_truth_cluster_count": metric_values["expected_cluster_count"],
        "algorithm_generated_cluster_count": metric_values["predicted_cluster_count"],
        "cluster_count_difference": (
            int(metric_values["predicted_cluster_count"])
            - int(metric_values["expected_cluster_count"])
        ),
    }

    majority: dict[int, str] = {}
    labels_by_cluster: dict[int, Counter[str]] = defaultdict(Counter)
    for label, assignment in zip(expected, assignments, strict=True):
        labels_by_cluster[assignment.cluster_id][label] += 1
    for cluster_id, counts in labels_by_cluster.items():
        majority[cluster_id] = counts.most_common(1)[0][0]
    details = [
        {
            "article_id": article["id"],
            "title": article["title"],
            "expected_cluster": article["expected_cluster"],
            "predicted_cluster": assignment.cluster_id,
            "assignment_similarity": round(assignment.similarity, 6),
            "predicted_majority_label": majority[assignment.cluster_id],
            "matches_predicted_majority": article["expected_cluster"] == majority[assignment.cluster_id],
        }
        for article, assignment in zip(articles, assignments, strict=True)
    ]
    sweep = [
        _metric_row(expected, online_centroid_cluster(vectors, value), value)
        for value in DEFAULT_SWEEP
    ]

    summary_path = args.output_dir / "clustering_benchmark_summary.csv"
    details_path = args.output_dir / "clustering_benchmark_details.csv"
    sweep_path = args.output_dir / "clustering_threshold_sweep.csv"
    history_path = args.output_dir / "clustering_benchmark_history.csv"
    snapshots = args.output_dir / "clustering_runs"
    _write_rows(summary_path, [summary])
    _write_rows(details_path, details)
    _write_rows(sweep_path, sweep)
    _append_row(history_path, summary)
    _write_rows(snapshots / f"{benchmark_run_id}_summary.csv", [summary])
    _write_rows(snapshots / f"{benchmark_run_id}_details.csv", details)
    _write_rows(snapshots / f"{benchmark_run_id}_threshold_sweep.csv", sweep)
    print(
        "Result: "
        f"precision={metric_values['pairwise_precision']:.3f} "
        f"recall={metric_values['pairwise_recall']:.3f} "
        f"f1={metric_values['pairwise_f1']:.3f} "
        f"purity={metric_values['purity']:.3f}",
        flush=True,
    )
    for path in (summary_path, details_path, sweep_path, history_path):
        print(f"Wrote {path.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
