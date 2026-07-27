from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from app.ai.schemas import (
    ClaimExtractionResult,
    ClassificationResult,
    EvidenceComparisonResult,
    EvidencePairInput,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[T]):
    value: T
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    request_id: str | None
    input_tokens: int | None
    elapsed_ms: float


class ClassificationProvider(Protocol):
    provider_name: str
    model: str

    def classify(
        self, *, title: str, content: str
    ) -> ProviderResult[ClassificationResult]: ...


class EmbeddingProvider(Protocol):
    provider_name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


class ClaimExtractionProvider(Protocol):
    provider_name: str
    model: str

    def extract_claims(
        self, *, article_id: int, title: str, content: str
    ) -> ProviderResult[ClaimExtractionResult]: ...


class EvidenceComparisonProvider(Protocol):
    provider_name: str
    model: str

    def compare(
        self,
        *,
        article_titles: dict[int, str],
        pairs: list[EvidencePairInput],
    ) -> ProviderResult[EvidenceComparisonResult]: ...


@dataclass(slots=True)
class ModelProviders:
    """Runtime-only provider bundle; never store provider clients in graph state."""

    classification: ClassificationProvider | None = None
    embedding: EmbeddingProvider | None = None
    claim_extraction: ClaimExtractionProvider | None = None
    evidence_comparison: EvidenceComparisonProvider | None = None
