from dataclasses import dataclass
from typing import Protocol


class ClassificationProvider(Protocol):
    def classify(self, *, title: str, content: str) -> dict[str, object]: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ClaimExtractionProvider(Protocol):
    def extract_claims(self, *, article_id: int, content: str) -> list[dict[str, object]]: ...


class EvidenceComparisonProvider(Protocol):
    def compare(self, *, claims: list[dict[str, object]]) -> dict[str, object]: ...


@dataclass(slots=True)
class ModelProviders:
    """Runtime-only provider bundle; never store provider clients in graph state."""

    classification: ClassificationProvider | None = None
    embedding: EmbeddingProvider | None = None
    claim_extraction: ClaimExtractionProvider | None = None
    evidence_comparison: EvidenceComparisonProvider | None = None
