from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClassificationResult(StrictModel):
    content_type: Literal["news", "analysis", "opinion", "tutorial", "other"]
    is_news: bool
    topics: list[str] = Field(max_length=8)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_content_type(cls, value: object) -> object:
        """Keep provider vocabulary inside the application's fixed taxonomy."""
        if not isinstance(value, dict):
            return value
        raw_content_type = value.get("content_type")
        if not isinstance(raw_content_type, str):
            return value

        normalized = raw_content_type.strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "news": "news",
            "breaking_news": "news",
            "news_report": "news",
            "report": "news",
            "reporting": "news",
            "current_events": "news",
            "analysis": "analysis",
            "news_analysis": "analysis",
            "explainer": "analysis",
            "in_depth": "analysis",
            "opinion": "opinion",
            "op_ed": "opinion",
            "editorial": "opinion",
            "commentary": "opinion",
            "tutorial": "tutorial",
            "how_to": "tutorial",
            "guide": "tutorial",
            "step_by_step": "tutorial",
            "other": "other",
        }
        canonical = aliases.get(normalized)
        if canonical is None:
            # A model sometimes puts a subject such as "politics" or
            # "technology" in content_type. Subjects belong in topics. When the
            # same output says this is news, preserve that signal; otherwise the
            # last-resort category is other.
            canonical = "news" if value.get("is_news") is True else "other"
        normalized_value = dict(value)
        normalized_value["content_type"] = canonical
        return normalized_value


class ExtractedClaim(StrictModel):
    claim_text: str = Field(min_length=5, max_length=1000)
    claim_type: Literal["factual", "numeric", "attributed", "prediction", "opinion"]
    supporting_excerpt: str = Field(min_length=5, max_length=2000)
    attribution: str | None = Field(max_length=500)
    primary_source_url: str | None = Field(max_length=2000)
    confidence: float = Field(ge=0, le=1)


class ClaimExtractionResult(StrictModel):
    claims: list[ExtractedClaim] = Field(max_length=30)


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
    links: list[EvidenceLinkResult] = Field(max_length=20)
    batch_summary: str = Field(min_length=5, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class CoverageDecision(StrictModel):
    needed: bool
    reason: str = Field(min_length=3, max_length=800)
    evidence_ids: list[Annotated[int, Field(gt=0)]] = Field(max_length=3)

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> "CoverageDecision":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Coverage evidence_ids must be unique")
        return self


class SupplementCoverageAssessment(StrictModel):
    earlier_events_and_timeline: CoverageDecision
    affected_people_and_effects: CoverageDecision
    missing_information_from_other_reporting: CoverageDecision
    disagreement_or_uncertainty: CoverageDecision


SearchPurpose = Literal[
    "earlier_events_and_timeline",
    "affected_people_and_effects",
    "missing_information_from_other_reporting",
    "disagreement_or_uncertainty",
]


class SearchToolArguments(StrictModel):
    purpose: SearchPurpose
    event: str = Field(min_length=3, max_length=240)
    entities: list[str] = Field(max_length=8)
    keywords: list[str] = Field(min_length=1, max_length=10)
    start_date: date | None
    end_date: date | None
    preferred_domains: list[str] = Field(max_length=8)
    max_results: int = Field(ge=1, le=8)

    @field_validator("event")
    @classmethod
    def normalize_event(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("event must contain meaningful text")
        return normalized

    @field_validator("entities", "keywords")
    @classmethod
    def normalize_search_terms(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 100 for value in normalized):
            raise ValueError("search terms must contain 1 to 100 characters")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("search terms must be unique")
        return normalized

    @field_validator("preferred_domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold().removeprefix("www.") for value in values]
        if any(
            not value
            or "://" in value
            or "/" in value
            or " " in value
            or "." not in value
            for value in normalized
        ):
            raise ValueError("preferred_domains must contain hostnames only")
        if len(set(normalized)) != len(normalized):
            raise ValueError("preferred_domains must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> "SearchToolArguments":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class CollectChunkArguments(StrictModel):
    source_call_id: str = Field(min_length=1, max_length=80)
    max_chunks: int = Field(ge=1, le=20)


class SearchLocalToolCall(StrictModel):
    call_id: str = Field(min_length=1, max_length=80)
    name: Literal["search_local"]
    arguments: SearchToolArguments


class WebSearchToolCall(StrictModel):
    call_id: str = Field(min_length=1, max_length=80)
    name: Literal["web_search"]
    arguments: SearchToolArguments


class MCPGovernmentSearchToolCall(StrictModel):
    call_id: str = Field(min_length=1, max_length=80)
    name: Literal["mcp_government_search"]
    arguments: SearchToolArguments


class CollectChunkToolCall(StrictModel):
    call_id: str = Field(min_length=1, max_length=80)
    name: Literal["collect_chunk"]
    arguments: CollectChunkArguments


SupplementToolCall = Annotated[
    SearchLocalToolCall
    | WebSearchToolCall
    | MCPGovernmentSearchToolCall
    | CollectChunkToolCall,
    Field(discriminator="name"),
]


class SupplementPlan(StrictModel):
    supplement_needed: bool
    coverage: SupplementCoverageAssessment
    next_step: Literal["use_tools", "compose", "stop"]
    tool_calls: list[SupplementToolCall] = Field(max_length=2)
    reason: str = Field(min_length=3, max_length=1500)

    @model_validator(mode="after")
    def validate_tool_sequence(self) -> "SupplementPlan":
        if not self.supplement_needed:
            if self.next_step != "stop" or self.tool_calls:
                raise ValueError(
                    "No-supplement plans must stop without tool calls"
                )
            return self
        if self.next_step == "use_tools":
            if len(self.tool_calls) != 2:
                raise ValueError(
                    "Tool steps require one search call and one collect_chunk call"
                )
            search_call, collect_call = self.tool_calls
            if search_call.call_id == collect_call.call_id:
                raise ValueError("Tool call IDs must be unique")
            if search_call.name == "collect_chunk" or collect_call.name != "collect_chunk":
                raise ValueError("collect_chunk must follow exactly one search call")
            if collect_call.arguments.source_call_id != search_call.call_id:
                raise ValueError("collect_chunk must reference the search call_id")
        elif self.tool_calls:
            raise ValueError("compose/stop steps cannot include tool calls")
        return self


class SupplementStatementDraft(StrictModel):
    text: str = Field(min_length=5, max_length=1200)
    evidence_ids: list[int] = Field(min_length=1, max_length=5)


class SupplementCardDraft(StrictModel):
    card_type: Literal[
        "background",
        "timeline",
        "practical_impact",
        "missing_context",
        "uncertainty",
    ]
    heading: str = Field(min_length=2, max_length=120)
    statements: list[SupplementStatementDraft] = Field(max_length=8)


class SupplementDraft(StrictModel):
    cards: list[SupplementCardDraft] = Field(max_length=6)


class SupplementStatementVerification(StrictModel):
    card_index: int = Field(ge=0)
    statement_index: int = Field(ge=0)
    supported: bool
    evidence_ids: list[int] = Field(max_length=5)
    reason: str = Field(min_length=2, max_length=1000)

    @model_validator(mode="after")
    def validate_support_evidence(self) -> "SupplementStatementVerification":
        if self.supported and not self.evidence_ids:
            raise ValueError("Supported statements require at least one evidence_id")
        if not self.supported and self.evidence_ids:
            raise ValueError("Unsupported statements must return an empty evidence_ids list")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Verification evidence_ids must be unique")
        return self


class SupplementVerification(StrictModel):
    statements: list[SupplementStatementVerification] = Field(max_length=48)

    @model_validator(mode="after")
    def require_unique_statement_coordinates(self) -> "SupplementVerification":
        coordinates = [
            (statement.card_index, statement.statement_index)
            for statement in self.statements
        ]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("Verification statement coordinates must be unique")
        return self
