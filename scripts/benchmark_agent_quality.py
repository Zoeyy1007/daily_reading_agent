"""Evaluate configured AI providers against a small labeled mock benchmark.

This script makes real model/embedding API calls but does not write mock data to
PostgreSQL. It evaluates classification, clustering, grounded claim extraction,
claim comparison, hybrid retrieval, supplement need, and bounded tool choice.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.factory import build_model_providers, build_supplement_provider  # noqa: E402
from app.ai.schemas import EvidenceClaimInput, EvidencePairInput  # noqa: E402
from app.agent.tool_policy import load_supplement_tool_policy  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.phase_five_service import (  # noqa: E402
    _bm25_scores,
    _normalize_scores,
)
from scripts.benchmark_clustering import (  # noqa: E402
    clustering_metrics,
    cosine_similarity,
    online_centroid_cluster,
)

DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "agent_quality_benchmark.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "metrics" / "results"


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return _safe_ratio(2 * precision * recall, precision + recall)


def classification_metrics(
    expected: Sequence[str], predicted: Sequence[str]
) -> dict[str, float]:
    labels = sorted(set(expected) | set(predicted))
    per_label_f1: list[float] = []
    correct = sum(left == right for left, right in zip(expected, predicted, strict=True))
    for label in labels:
        true_positive = sum(
            left == label and right == label
            for left, right in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            left != label and right == label
            for left, right in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            left == label and right != label
            for left, right in zip(expected, predicted, strict=True)
        )
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        per_label_f1.append(_f1(precision, recall))
    return {
        "accuracy": _safe_ratio(correct, len(expected)),
        "macro_f1": sum(per_label_f1) / len(per_label_f1) if per_label_f1 else 1.0,
    }


def retrieval_metrics(
    ranked_ids: Sequence[str], relevant_ids: set[str], *, k: int
) -> dict[str, float]:
    top = list(ranked_ids[:k])
    hits = sum(item in relevant_ids for item in top)
    reciprocal_rank = next(
        (1.0 / index for index, item in enumerate(ranked_ids, start=1) if item in relevant_ids),
        0.0,
    )
    return {
        "precision_at_k": _safe_ratio(hits, len(top)),
        "recall_at_k": _safe_ratio(hits, len(relevant_ids)),
        "mrr": reciprocal_rank,
    }


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _claim_matches(expected: dict[str, object], claim_text: str, excerpt: str) -> bool:
    searchable = _normalized(f"{claim_text} {excerpt}")
    return all(
        _normalized(str(term)) in searchable for term in expected.get("required_terms", [])
    )


def _grounded(excerpt: str, article: str) -> bool:
    return bool(excerpt.strip()) and _normalized(excerpt) in _normalized(article)


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _article_text(article: dict[str, object]) -> str:
    return f"Title: {article['title']}\nArticle: {article['content']}"


def _coverage_gaps(plan: object) -> set[str]:
    coverage = getattr(plan, "coverage")
    return {
        name
        for name in (
            "earlier_events_and_timeline",
            "affected_people_and_effects",
            "missing_information_from_other_reporting",
            "disagreement_or_uncertainty",
        )
        if getattr(coverage, name).needed
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--retrieval-k", type=int, default=3)
    parser.add_argument("--skip-supplement", action="store_true")
    parser.add_argument("--suffix", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.retrieval_k < 1:
        raise SystemExit("--retrieval-k must be at least 1")
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    articles: list[dict[str, object]] = payload["articles"]
    settings = get_settings()
    providers = build_model_providers(settings)
    if providers.classification is None or providers.embedding is None:
        raise SystemExit("Classification and embedding providers are required")
    threshold = args.threshold or settings.story_cluster_similarity_threshold
    details: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "fixture": str(args.fixture),
        "article_count": len(articles),
    }
    benchmark_started = perf_counter()

    print(f"Classifying {len(articles)} mock articles...", flush=True)
    expected_types: list[str] = []
    predicted_types: list[str] = []
    expected_news: list[str] = []
    predicted_news: list[str] = []
    classification_seconds = 0.0
    for article in articles:
        result = providers.classification.classify(
            title=str(article["title"]), content=str(article["content"])
        )
        classification_seconds += result.elapsed_ms / 1000.0
        expected_type = str(article["expected_content_type"])
        predicted_type = result.value.content_type
        expected_types.append(expected_type)
        predicted_types.append(predicted_type)
        expected_news.append(str(bool(article["expected_is_news"])))
        predicted_news.append(str(result.value.is_news))
        details.append(
            {
                "stage": "classification",
                "case_id": article["id"],
                "expected": f"{expected_type}; is_news={article['expected_is_news']}",
                "predicted": f"{predicted_type}; is_news={result.value.is_news}",
                "correct": expected_type == predicted_type
                and bool(article["expected_is_news"]) == result.value.is_news,
                "elapsed_seconds": round(result.elapsed_ms / 1000.0, 6),
                "notes": ", ".join(result.value.topics),
            }
        )
    type_scores = classification_metrics(expected_types, predicted_types)
    news_scores = classification_metrics(expected_news, predicted_news)
    summary.update(
        {
            "classification_accuracy": type_scores["accuracy"],
            "classification_macro_f1": type_scores["macro_f1"],
            "is_news_accuracy": news_scores["accuracy"],
            "classification_total_seconds": classification_seconds,
            "classification_seconds_per_article": _safe_ratio(
                classification_seconds, len(articles)
            ),
        }
    )

    print("Embedding and clustering mock articles...", flush=True)
    embedding_result = providers.embedding.embed([_article_text(item) for item in articles])
    assignments = online_centroid_cluster(embedding_result.vectors, threshold)
    cluster_scores = clustering_metrics(
        [str(item["expected_cluster"]) for item in articles],
        [item.cluster_id for item in assignments],
    )
    summary.update(
        {
            "clustering_pairwise_precision": cluster_scores["pairwise_precision"],
            "clustering_pairwise_recall": cluster_scores["pairwise_recall"],
            "clustering_pairwise_f1": cluster_scores["pairwise_f1"],
            "clustering_purity": cluster_scores["purity"],
            "expected_cluster_count": cluster_scores["expected_cluster_count"],
            "predicted_cluster_count": cluster_scores["predicted_cluster_count"],
            "article_embedding_seconds": embedding_result.elapsed_ms / 1000.0,
            "article_embedding_seconds_per_embedding": _safe_ratio(
                embedding_result.elapsed_ms / 1000.0, len(articles)
            ),
        }
    )
    for article, assignment in zip(articles, assignments, strict=True):
        details.append(
            {
                "stage": "clustering",
                "case_id": article["id"],
                "expected": article["expected_cluster"],
                "predicted": assignment.cluster_id,
                "correct": "see pairwise metrics",
                "elapsed_seconds": "",
                "notes": f"similarity={assignment.similarity:.4f}",
            }
        )

    claim_expected = claim_matched = claim_predicted = claim_grounded = 0
    claim_seconds = 0.0
    if providers.claim_extraction is not None:
        claim_articles = [item for item in articles if item.get("expected_claims")]
        print(f"Extracting claims from {len(claim_articles)} mock articles...", flush=True)
        for article in claim_articles:
            result = providers.claim_extraction.extract_claims(
                article_id=int(article["numeric_id"]),
                title=str(article["title"]),
                content=str(article["content"]),
            )
            claim_seconds += result.elapsed_ms / 1000.0
            expected_claims: list[dict[str, object]] = article["expected_claims"]  # type: ignore[assignment]
            predicted_claims = result.value.claims
            claim_expected += len(expected_claims)
            claim_predicted += len(predicted_claims)
            claim_grounded += sum(
                _grounded(claim.supporting_excerpt, str(article["content"]))
                for claim in predicted_claims
            )
            unused = set(range(len(predicted_claims)))
            matched = 0
            for expected_claim in expected_claims:
                match = next(
                    (
                        index
                        for index in unused
                        if _claim_matches(
                            expected_claim,
                            predicted_claims[index].claim_text,
                            predicted_claims[index].supporting_excerpt,
                        )
                    ),
                    None,
                )
                if match is not None:
                    unused.remove(match)
                    matched += 1
            claim_matched += matched
            details.append(
                {
                    "stage": "claim_extraction",
                    "case_id": article["id"],
                    "expected": len(expected_claims),
                    "predicted": len(predicted_claims),
                    "correct": f"matched={matched}",
                    "elapsed_seconds": round(result.elapsed_ms / 1000.0, 6),
                    "notes": " | ".join(claim.claim_text for claim in predicted_claims),
                }
            )
    summary.update(
        {
            "claim_expected_count": claim_expected,
            "claim_predicted_count": claim_predicted,
            "claim_keyword_recall": _safe_ratio(claim_matched, claim_expected),
            "claim_match_precision": _safe_ratio(claim_matched, claim_predicted),
            "claim_grounding_rate": _safe_ratio(claim_grounded, claim_predicted),
            "claim_extraction_total_seconds": claim_seconds,
            "claim_extraction_seconds_per_article": _safe_ratio(
                claim_seconds,
                sum(bool(item.get("expected_claims")) for item in articles),
            ),
        }
    )

    comparison_cases: list[dict[str, object]] = payload["evidence_pairs"]
    comparison_correct = 0
    comparison_seconds = 0.0
    if providers.evidence_comparison is not None and comparison_cases:
        print(f"Comparing {len(comparison_cases)} labeled claim pairs...", flush=True)
        pairs = [
            EvidencePairInput(
                pair_id=int(item["pair_id"]),
                left=EvidenceClaimInput(
                    claim_id=int(item["left_claim_id"]),
                    article_id=int(item["left_article_id"]),
                    claim_text=str(item["left"]),
                ),
                right=EvidenceClaimInput(
                    claim_id=int(item["right_claim_id"]),
                    article_id=int(item["right_article_id"]),
                    claim_text=str(item["right"]),
                ),
                retrieval_score=1.0,
            )
            for item in comparison_cases
        ]
        result = providers.evidence_comparison.compare(
            article_titles={
                int(item["left_article_id"]): f"Mock article {item['left_article_id']}"
                for item in comparison_cases
            }
            | {
                int(item["right_article_id"]): f"Mock article {item['right_article_id']}"
                for item in comparison_cases
            },
            pairs=pairs,
        )
        comparison_seconds = result.elapsed_ms / 1000.0
        links = {
            (link.left_claim_id, link.right_claim_id): link
            for link in result.value.links
        }
        for item in comparison_cases:
            link = links.get((int(item["left_claim_id"]), int(item["right_claim_id"])))
            predicted = link.relationship if link else "missing"
            correct = predicted == item["expected_relationship"]
            comparison_correct += correct
            details.append(
                {
                    "stage": "evidence_comparison",
                    "case_id": item["pair_id"],
                    "expected": item["expected_relationship"],
                    "predicted": predicted,
                    "correct": correct,
                    "elapsed_seconds": round(
                        comparison_seconds / len(comparison_cases), 6
                    ),
                    "notes": link.rationale if link else "Model omitted this pair",
                }
            )
    summary.update(
        {
            "evidence_comparison_accuracy": _safe_ratio(
                comparison_correct, len(comparison_cases)
            ),
            "evidence_comparison_total_seconds": comparison_seconds,
            "evidence_comparison_seconds_per_pair": _safe_ratio(
                comparison_seconds, len(comparison_cases)
            ),
        }
    )

    retrieval_cases: list[dict[str, object]] = payload["retrieval_cases"]
    retrieval_totals: Counter[str] = Counter()
    retrieval_seconds = 0.0
    print(f"Evaluating {len(retrieval_cases)} hybrid retrieval cases...", flush=True)
    for case in retrieval_cases:
        chunks: list[dict[str, object]] = case["chunks"]  # type: ignore[assignment]
        started = perf_counter()
        embedded = providers.embedding.embed(
            [str(case["query"]), *[str(chunk["text"]) for chunk in chunks]]
        )
        query_vector, *chunk_vectors = embedded.vectors
        bm25 = _normalize_scores(
            _bm25_scores(str(case["query"]), [str(chunk["text"]) for chunk in chunks])
        )
        vectors = [
            max(0.0, min(1.0, (cosine_similarity(query_vector, vector) + 1.0) / 2.0))
            for vector in chunk_vectors
        ]
        total_weight = settings.evidence_bm25_weight + settings.evidence_vector_weight
        bm25_weight = (
            settings.evidence_bm25_weight / total_weight if total_weight else 0.5
        )
        vector_weight = (
            settings.evidence_vector_weight / total_weight if total_weight else 0.5
        )
        ranked = sorted(
            zip(chunks, bm25, vectors, strict=True),
            key=lambda row: bm25_weight * row[1] + vector_weight * row[2],
            reverse=True,
        )
        elapsed = perf_counter() - started
        retrieval_seconds += elapsed
        relevant = {str(chunk["id"]) for chunk in chunks if chunk["relevant"]}
        scores = retrieval_metrics(
            [str(row[0]["id"]) for row in ranked], relevant, k=args.retrieval_k
        )
        for name, value in scores.items():
            retrieval_totals[name] += value
        details.append(
            {
                "stage": "retrieval",
                "case_id": case["id"],
                "expected": ",".join(sorted(relevant)),
                "predicted": ",".join(str(row[0]["id"]) for row in ranked[: args.retrieval_k]),
                "correct": f"recall@{args.retrieval_k}={scores['recall_at_k']:.3f}",
                "elapsed_seconds": round(elapsed, 6),
                "notes": f"MRR={scores['mrr']:.3f}",
            }
        )
    for name in ("precision_at_k", "recall_at_k", "mrr"):
        summary[f"retrieval_{name}"] = _safe_ratio(
            retrieval_totals[name], len(retrieval_cases)
        )
    summary["retrieval_total_seconds"] = retrieval_seconds
    summary["retrieval_seconds_per_case"] = _safe_ratio(
        retrieval_seconds, len(retrieval_cases)
    )

    supplement_cases: list[dict[str, object]] = payload["supplement_cases"]
    supplement_correct = tool_correct = gap_tp = gap_fp = gap_fn = 0
    supplement_seconds = 0.0
    if not args.skip_supplement:
        provider = build_supplement_provider(settings)
        policy = load_supplement_tool_policy(settings.supplement_tool_policy_path)
        tools = policy.llm_tool_list(["search_local", "web_search", "collect_chunk"])
        print(f"Evaluating {len(supplement_cases)} supplement decisions...", flush=True)
        for case in supplement_cases:
            result = provider.plan(
                article_title=str(case["title"]),
                article_content=str(case["content"]),
                cluster_event=str(case["cluster_event"]),
                evidence=[],
                tool_history=[],
                available_tools=tools,
                coverage_targets={
                    name: {"status": "unassessed"}
                    for name in (
                        "earlier_events_and_timeline",
                        "affected_people_and_effects",
                        "missing_information_from_other_reporting",
                        "disagreement_or_uncertainty",
                    )
                },
            )
            supplement_seconds += result.elapsed_ms / 1000.0
            plan = result.value
            expected_needed = bool(case["expected_needed"])
            supplement_correct += plan.supplement_needed == expected_needed
            expected_tool = case.get("expected_search_tool")
            predicted_tool = plan.tool_calls[0].name if plan.tool_calls else None
            if expected_needed:
                tool_correct += predicted_tool == expected_tool
            expected_gaps = set(case.get("expected_gaps", []))
            predicted_gaps = _coverage_gaps(plan)
            gap_tp += len(expected_gaps & predicted_gaps)
            gap_fp += len(predicted_gaps - expected_gaps)
            gap_fn += len(expected_gaps - predicted_gaps)
            details.append(
                {
                    "stage": "supplement_planning",
                    "case_id": case["id"],
                    "expected": f"needed={expected_needed}; tool={expected_tool}; gaps={sorted(expected_gaps)}",
                    "predicted": f"needed={plan.supplement_needed}; tool={predicted_tool}; gaps={sorted(predicted_gaps)}",
                    "correct": plan.supplement_needed == expected_needed
                    and (not expected_needed or predicted_tool == expected_tool),
                    "elapsed_seconds": round(result.elapsed_ms / 1000.0, 6),
                    "notes": plan.reason,
                }
            )
    needed_case_count = sum(bool(case["expected_needed"]) for case in supplement_cases)
    gap_precision = _safe_ratio(gap_tp, gap_tp + gap_fp)
    gap_recall = _safe_ratio(gap_tp, gap_tp + gap_fn)
    summary.update(
        {
            "supplement_decision_accuracy": (
                _safe_ratio(supplement_correct, len(supplement_cases))
                if not args.skip_supplement
                else "skipped"
            ),
            "supplement_tool_choice_accuracy": (
                _safe_ratio(tool_correct, needed_case_count)
                if not args.skip_supplement
                else "skipped"
            ),
            "supplement_gap_f1": (
                _f1(gap_precision, gap_recall) if not args.skip_supplement else "skipped"
            ),
            "supplement_total_seconds": supplement_seconds,
            "supplement_seconds_per_case": _safe_ratio(
                supplement_seconds,
                len(supplement_cases) if not args.skip_supplement else 0,
            ),
        }
    )

    summary["benchmark_wall_seconds"] = perf_counter() - benchmark_started
    suffix = f"_{args.suffix}" if args.suffix else ""
    output_dir = args.output_dir.resolve()
    summary_path = output_dir / f"agent_quality_summary{suffix}.csv"
    details_path = output_dir / f"agent_quality_details{suffix}.csv"
    _write_csv(
        summary_path,
        [
            {"metric": name, "value": value}
            for name, value in summary.items()
        ],
        ["metric", "value"],
    )
    _write_csv(
        details_path,
        details,
        [
            "stage",
            "case_id",
            "expected",
            "predicted",
            "correct",
            "elapsed_seconds",
            "notes",
        ],
    )
    print(f"Wrote {summary_path}", flush=True)
    print(f"Wrote {details_path}", flush=True)
    print(
        f"Classification accuracy={type_scores['accuracy']:.3f}; "
        f"clustering F1={cluster_scores['pairwise_f1']:.3f}; "
        f"claim recall={summary['claim_keyword_recall']:.3f}; "
        f"comparison accuracy={summary['evidence_comparison_accuracy']:.3f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
