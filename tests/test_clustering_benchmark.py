import json
from pathlib import Path

import pytest

from scripts.benchmark_clustering import (
    clustering_metrics,
    cosine_similarity,
    online_centroid_cluster,
)


def test_fixture_has_eight_balanced_event_clusters() -> None:
    fixture = Path(__file__).parent / "fixtures" / "clustering_benchmark_articles.json"
    articles = json.loads(fixture.read_text(encoding="utf-8"))
    labels = [article["expected_cluster"] for article in articles]

    assert len(articles) == 24
    assert len(set(labels)) == 8
    assert all(labels.count(label) == 3 for label in set(labels))


def test_online_clustering_and_metrics_for_separated_vectors() -> None:
    vectors = ([1.0, 0.0], [0.99, 0.01], [0.0, 1.0], [0.01, 0.99])
    assignments = online_centroid_cluster(vectors, threshold=0.9)
    predicted = [assignment.cluster_id for assignment in assignments]
    metrics = clustering_metrics(["a", "a", "b", "b"], predicted)

    assert predicted == [1, 1, 2, 2]
    assert metrics["pairwise_precision"] == pytest.approx(1.0)
    assert metrics["pairwise_recall"] == pytest.approx(1.0)
    assert metrics["pairwise_f1"] == pytest.approx(1.0)
    assert metrics["purity"] == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_pairwise_metrics_detect_merged_unrelated_clusters() -> None:
    metrics = clustering_metrics(["a", "a", "b", "b"], [1, 1, 1, 1])

    assert metrics["pairwise_recall"] == pytest.approx(1.0)
    assert metrics["pairwise_precision"] == pytest.approx(1 / 3)
    assert metrics["purity"] == pytest.approx(0.5)
