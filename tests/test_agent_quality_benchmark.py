from scripts.benchmark_agent_quality import classification_metrics, retrieval_metrics


def test_classification_metrics_report_accuracy_and_macro_f1() -> None:
    scores = classification_metrics(
        ["news", "news", "opinion", "tutorial"],
        ["news", "opinion", "opinion", "tutorial"],
    )

    assert scores["accuracy"] == 0.75
    assert 0 < scores["macro_f1"] < 1


def test_retrieval_metrics_report_precision_recall_and_mrr() -> None:
    scores = retrieval_metrics(["noise", "answer-1", "answer-2"], {"answer-1", "answer-2"}, k=2)

    assert scores["precision_at_k"] == 0.5
    assert scores["recall_at_k"] == 0.5
    assert scores["mrr"] == 0.5
