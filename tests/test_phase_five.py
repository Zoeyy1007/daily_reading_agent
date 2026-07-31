from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.ai.client import _inline_json_schema_refs
from app.ai.factory import build_model_providers
from app.ai.providers import EmbeddingResult, ProviderResult
from app.ai.schemas import (
    ClassificationResult,
    EvidenceComparisonResult,
    EvidenceLinkResult,
    EvidencePairInput,
    EvidenceClaimInput,
    ExtractedClaim,
)
from app.config import Settings
from app.services.phase_five_service import (
    _choose_representative,
    _bm25_scores,
    _excerpt_present,
    _select_claim_pairs,
    _select_cluster_articles,
    article_embedding_text,
    content_fingerprint,
    split_article_content,
)


class FakeEmbeddingProvider:
    provider_name = "fake"
    model = "fake-embedding"
    dimensions = 3

    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[float(index), 0.5, 1.0] for index, _text in enumerate(texts)],
            request_id="fake-request",
            input_tokens=len(texts),
            elapsed_ms=1.0,
        )


def test_chunking_overlaps_and_preserves_original_text() -> None:
    content = " ".join(f"word{index}" for index in range(25))
    chunks = split_article_content(content, target_words=10, overlap_words=2)
    assert [len(text.split()) for text, _start, _end in chunks] == [10, 10, 9]
    assert chunks[0][0].split()[-2:] == chunks[1][0].split()[:2]
    for text, start, end in chunks:
        assert content[start:end] == text


def test_excerpt_validation_tolerates_whitespace_not_invention() -> None:
    content = "The agency raised the rate by 0.25 percentage points."
    assert _excerpt_present("agency  raised the rate", content)
    assert not _excerpt_present("agency lowered the rate", content)


def test_structured_outputs_reject_unknown_fields_and_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(
            {
                "content_type": "news",
                "is_news": True,
                "topics": [],
                "confidence": 1.5,
                "invented": "field",
            }
        )
    claim = ExtractedClaim(
        claim_text="The rate increased.",
        claim_type="factual",
        supporting_excerpt="The rate increased.",
        attribution=None,
        primary_source_url=None,
        confidence=0.9,
    )
    assert claim.attribution is None


@pytest.mark.parametrize(
    ("provider_value", "is_news", "expected"),
    [
        ("news report", True, "news"),
        ("explainer", False, "analysis"),
        ("editorial", False, "opinion"),
        ("how-to", False, "tutorial"),
        ("politics", True, "news"),
        ("uncategorized-format", False, "other"),
    ],
)
def test_classification_content_type_is_normalized(
    provider_value: str, is_news: bool, expected: str
) -> None:
    result = ClassificationResult.model_validate(
        {
            "content_type": provider_value,
            "is_news": is_news,
            "topics": ["politics"],
            "confidence": 0.8,
        }
    )

    assert result.content_type == expected


def test_evidence_output_is_relational_not_json_blob() -> None:
    output = EvidenceComparisonResult(
        links=[
            EvidenceLinkResult(
                left_claim_id=10,
                right_claim_id=20,
                relationship="supports",
                confidence=0.9,
                rationale="Both report the same measured increase.",
            )
        ],
        batch_summary="The reports agree on the measured increase.",
        confidence=0.85,
    )
    assert output.links[0].left_claim_id == 10


def test_nested_evidence_schema_is_inlined_for_kimi() -> None:
    schema = _inline_json_schema_refs(EvidenceComparisonResult.model_json_schema())

    assert "$defs" not in schema
    assert "$ref" not in str(schema)
    link_properties = schema["properties"]["links"]["items"]["properties"]
    assert "left_claim_id" in link_properties
    assert "relationship" in link_properties


def test_evidence_pair_input_keeps_comparison_bounded() -> None:
    pair = EvidencePairInput(
        pair_id=1,
        left=EvidenceClaimInput(
            claim_id=10, article_id=1, claim_text="The bridge opened Monday."
        ),
        right=EvidenceClaimInput(
            claim_id=20, article_id=2, claim_text="Officials opened it Monday."
        ),
        retrieval_score=0.91,
    )
    assert pair.left.article_id != pair.right.article_id


def test_embedding_provider_contract_and_article_representation() -> None:
    provider = FakeEmbeddingProvider()
    result = provider.embed(["first", "second"])
    assert len(result.vectors) == 2
    article = SimpleNamespace(
        title="A title",
        rss_summary="A summary",
        content_text="Full article text",
    )
    representation = article_embedding_text(article)  # type: ignore[arg-type]
    assert "A title" in representation
    assert "A summary" in representation


def test_retention_is_capped_and_fingerprints_are_stable() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, selected_evidence_retention_days=31)
    assert content_fingerprint("a", "b") == content_fingerprint("a", "b")
    assert content_fingerprint("a", "b") != content_fingerprint("b", "a")


def test_deepseek_can_fill_evidence_role_without_kimi_key() -> None:
    settings = Settings(
        _env_file=None,
        dashscope_api_key="qwen-test-key",
        qwen_base_url="https://qwen.invalid/v1",
        deepseek_api_key="deepseek-test-key",
        evidence_comparison_provider="deepseek",
        evidence_comparison_model="deepseek-v4-pro",
    )

    providers = build_model_providers(settings)

    assert providers.evidence_comparison is not None
    assert providers.evidence_comparison.provider_name == "deepseek"
    assert providers.evidence_comparison.model == "deepseek-v4-pro"


def test_representative_selection_uses_evidence_and_coverage() -> None:
    claims = [
        SimpleNamespace(id=1, article_id=10, confidence=0.9),
        SimpleNamespace(id=2, article_id=20, confidence=0.9),
        SimpleNamespace(id=3, article_id=20, confidence=0.8),
    ]
    links = [
        EvidenceLinkResult(
            left_claim_id=1,
            right_claim_id=2,
            relationship="equivalent",
            confidence=0.95,
            rationale="Both state the same event.",
        )
    ]

    representative_id, reason = _choose_representative(
        claims, links, {10: 500, 20: 700}  # type: ignore[arg-type]
    )

    assert representative_id == 20
    assert "deterministically" in reason


def test_bm25_rewards_query_terms() -> None:
    scores = _bm25_scores(
        "bridge opened",
        ["The bridge opened Monday.", "A recipe for tomato soup."],
    )
    assert scores[0] > scores[1]


def test_cluster_pruning_caps_articles_and_preserves_sources() -> None:
    articles = [
        SimpleNamespace(id=index, source_id=(index % 3) + 1, embedding=[1.0, index / 100])
        for index in range(1, 9)
    ]
    selected = _select_cluster_articles(
        articles,  # type: ignore[arg-type]
        article_groups={article.id: article.source_id for article in articles},
        centroid=[1.0, 0.0],
        max_articles=5,
        redundancy_threshold=0.99999,
    )
    selected_sources = {
        article.source_id for article in articles if article.id in selected
    }
    assert len(selected) <= 5
    assert selected_sources == {1, 2, 3}


def test_claim_pair_retrieval_is_cross_source_and_capped() -> None:
    claims = [
        SimpleNamespace(
            id=index,
            article_id=index,
            claim_text=f"The bridge opened Monday number {index}",
            embedding=[1.0, index / 10],
        )
        for index in range(1, 7)
    ]
    sources = {index: index % 3 for index in range(1, 7)}
    pairs = _select_claim_pairs(
        claims, sources, max_pairs=4  # type: ignore[arg-type]
    )
    assert len(pairs) == 4
    assert all(
        sources[pair.left.article_id] != sources[pair.right.article_id]
        for pair in pairs
    )
