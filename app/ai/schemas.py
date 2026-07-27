from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassificationResult(StrictModel):
    content_type: Literal["news", "analysis", "opinion", "tutorial", "other"]
    is_news: bool
    topics: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)


class ExtractedClaim(StrictModel):
    claim_text: str = Field(min_length=5, max_length=1000)
    claim_type: Literal["factual", "numeric", "attributed", "prediction", "opinion"]
    supporting_excerpt: str = Field(min_length=5, max_length=2000)
    attribution: str | None = Field(default=None, max_length=500)
    primary_source_url: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class ClaimExtractionResult(StrictModel):
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=30)


class EvidenceClaimInput(StrictModel):
    claim_id: int
    article_id: int
    claim_text: str
    attribution: str | None = None


class EvidencePairInput(StrictModel):
    pair_id: int
    left: EvidenceClaimInput
    right: EvidenceClaimInput
    retrieval_score: float = Field(ge=0, le=1)


class EvidenceLinkResult(StrictModel):
    left_claim_id: int
    right_claim_id: int
    relationship: Literal["equivalent", "supports", "contradicts", "related", "unrelated"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=3, max_length=2000)


class EvidenceComparisonResult(StrictModel):
    links: list[EvidenceLinkResult] = Field(default_factory=list, max_length=20)
    batch_summary: str = Field(min_length=5, max_length=2000)
    confidence: float = Field(ge=0, le=1)
