from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StoryClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    representative_title: str
    event_summary: str | None
    event_date: date
    representative_article_id: int | None
    comparison_status: str
    embedding_model: str
    expires_at: datetime
    member_count: int


class ClusterMemberRead(BaseModel):
    article_id: int
    title: str
    source_id: int
    similarity_score: float
    relationship: str


class ArticleClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    claim_text: str
    claim_type: str
    supporting_excerpt: str
    attribution: str | None
    primary_source_url: str | None
    confidence: float
    provider: str
    model: str


class ClaimLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    left_claim_id: int
    right_claim_id: int
    relationship: str
    confidence: float
    rationale: str


class ClusterComparisonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    representative_article_id: int
    shared_claim_count: int
    disputed_claim_count: int
    unsupported_claim_count: int
    selection_reason: str
    confidence: float
    provider: str
    model: str
    expires_at: datetime


class StoryClusterDetail(StoryClusterRead):
    members: list[ClusterMemberRead]
    claims: list[ArticleClaimRead]
    links: list[ClaimLinkRead]
    comparison: ClusterComparisonRead | None


class ModelCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    role: str
    provider: str
    model: str
    status: str
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: float | None
    error: str | None
    created_at: datetime
