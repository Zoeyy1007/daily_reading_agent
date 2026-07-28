from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class SupplementCitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    evidence_item_id: int
    statement_index: int
    citation_order: int
    statement_text: str


class SupplementCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_type: str
    heading: str
    summary_text: str
    word_count: int
    display_order: int
    verification_status: str
    citations: list[SupplementCitationRead]


class SupplementEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_article_id: int | None
    source_chunk_id: int | None
    query: str
    title: str
    publisher: str
    url: str
    published_at: datetime | None
    excerpt: str
    retrieval_score: float
    reliability_status: str
    selected: bool
    jurisdiction: str | None
    agency: str | None
    document_type: str | None
    document_identifier: str | None
    effective_date: date | None
    retrieved_at: datetime


class SupplementRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    daily_reading_item_id: int
    daily_run_id: int | None
    status: str
    detected_gaps: str | None
    decision_reason: str | None
    tool_history: str | None
    original_word_count: int
    word_budget: int
    iteration_count: int
    tool_call_count: int
    last_error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    evidence_items: list[SupplementEvidenceRead]
    cards: list[SupplementCardRead]
