from datetime import date

import pytest
from pydantic import ValidationError

from app.ai.client import OpenAICompatibleClient, StructuredOutputError
from app.ai.schemas import (
    CollectChunkArguments,
    CollectChunkToolCall,
    CoverageDecision,
    SearchLocalToolCall,
    SearchToolArguments,
    SupplementCardDraft,
    SupplementCoverageAssessment,
    SupplementDraft,
    SupplementPlan,
    SupplementStatementDraft,
    SupplementStatementVerification,
    SupplementVerification,
    WebSearchToolCall,
)
from app.config import Settings
from app.agent.tool_policy import load_supplement_tool_policy
from app.agent.tool_executor import (
    ToolCallRejected,
    build_search_query,
    extract_tool_pair,
)
from app.services.supplement_service import (
    MAX_EVIDENCE_PER_COVERAGE_AREA,
    _coverage_research_complete,
    _coverage_target_payload,
    _update_coverage_ledger,
    is_supplement_eligible,
    supported_statement_rows,
    validate_verification_contract,
    VerificationContractError,
)
from app.tools.supplement_search import collect_chunk, domain_allowed
from app.tools.tavily_provider import TavilySearchProvider


def _draft() -> SupplementDraft:
    return SupplementDraft(
        cards=[
            SupplementCardDraft(
                card_type="practical_impact",
                heading="Who is affected",
                statements=[
                    SupplementStatementDraft(
                        text="The agency estimates the change affects 20,000 households.",
                        evidence_ids=[10],
                    ),
                    SupplementStatementDraft(
                        text="The change will certainly improve the economy for everyone.",
                        evidence_ids=[11],
                    ),
                ],
            )
        ]
    )


def test_grounding_keeps_only_verified_statements_and_valid_citations() -> None:
    verification = SupplementVerification(
        statements=[
            SupplementStatementVerification(
                card_index=0,
                statement_index=0,
                supported=True,
                evidence_ids=[10],
                reason="The excerpt directly contains the attributed estimate.",
            ),
            SupplementStatementVerification(
                card_index=0,
                statement_index=1,
                supported=False,
                evidence_ids=[],
                reason="This is unsupported causal speculation.",
            ),
        ]
    )

    rows = supported_statement_rows(
        _draft(), verification, valid_evidence_ids={10, 11}, word_budget=100
    )

    assert len(rows) == 1
    assert rows[0][4] == [10]
    assert "agency estimates" in rows[0][3]


def test_word_budget_keeps_whole_statements_and_never_truncates_claims() -> None:
    verification = SupplementVerification(
        statements=[
            SupplementStatementVerification(
                card_index=0,
                statement_index=0,
                supported=True,
                evidence_ids=[10],
                reason="Supported.",
            )
        ]
    )
    assert supported_statement_rows(
        _draft(), verification, valid_evidence_ids={10}, word_budget=3
    ) == []


def test_external_evidence_requires_an_allowed_domain() -> None:
    domains = {"reuters.com", "gov.uk"}
    assert domain_allowed("https://www.reuters.com/world/story", domains)
    assert domain_allowed("https://consult.gov.uk/document.pdf", domains)
    assert not domain_allowed("https://reuters.com.example.org/story", domains)
    assert not domain_allowed("https://unknown.example/story", set())


def test_collect_chunk_is_bounded_and_has_a_stable_content_hash() -> None:
    first = collect_chunk(
        text="one two three four five", url="https://example.gov/doc", max_words=3
    )
    second = collect_chunk(
        text="one  two\nthree four five", url="https://example.gov/doc", max_words=3
    )

    assert first.excerpt == "one two three"
    assert first.content_hash == second.content_hash


def test_supplement_word_ratio_cannot_exceed_half_the_article() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, supplement_word_ratio=0.51)


def test_default_yaml_policy_exposes_only_bounded_callable_search_tools() -> None:
    load_supplement_tool_policy.cache_clear()
    policy = load_supplement_tool_policy("config/supplement_tools.yaml")

    assert policy.tool("search_local").enabled
    assert policy.tool("search_local").max_calls_per_article == 2
    assert policy.tool("collect_chunk").agent_callable
    assert policy.tool("web_search").enabled
    assert policy.tool("mcp_government_search").permissions.allowed_domain_set


def test_supplements_are_eligible_only_for_saved_news_classification() -> None:
    news = type("Classification", (), {"is_news": True})()
    not_news = type("Classification", (), {"is_news": False})()

    assert is_supplement_eligible(news)  # type: ignore[arg-type]
    assert not is_supplement_eligible(not_news)  # type: ignore[arg-type]
    assert not is_supplement_eligible(None)


def _coverage() -> SupplementCoverageAssessment:
    return SupplementCoverageAssessment(
        earlier_events_and_timeline=CoverageDecision(
            needed=True, reason="Earlier events are absent.", evidence_ids=[]
        ),
        affected_people_and_effects=CoverageDecision(
            needed=True, reason="Affected groups are not identified.", evidence_ids=[]
        ),
        missing_information_from_other_reporting=CoverageDecision(
            needed=False, reason="No material omission is apparent yet.", evidence_ids=[]
        ),
        disagreement_or_uncertainty=CoverageDecision(
            needed=False, reason="No disagreement is described.", evidence_ids=[]
        ),
    )


def _search_arguments(
    *,
    purpose: str = "earlier_events_and_timeline",
    preferred_domains: list[str] | None = None,
) -> SearchToolArguments:
    return SearchToolArguments.model_validate(
        {
            "purpose": purpose,
            "event": "Federal vehicle emissions rule",
            "entities": ["Environmental Protection Agency"],
            "keywords": ["vehicle emissions", "final rule"],
            "start_date": date(2025, 1, 1),
            "end_date": date(2026, 7, 30),
            "preferred_domains": preferred_domains or [],
            "max_results": 5,
        }
    )


def test_strict_plan_allows_one_search_followed_by_collect_chunk() -> None:
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=_coverage(),
        next_step="use_tools",
        tool_calls=[
            SearchLocalToolCall(
                call_id="search-1",
                name="search_local",
                arguments=_search_arguments(),
            ),
            CollectChunkToolCall(
                call_id="collect-1",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-1", max_chunks=6
                ),
            ),
        ],
        reason="The article lacks useful context.",
    )

    assert len(plan.tool_calls) == 2
    policy = load_supplement_tool_policy("config/supplement_tools.yaml")
    extracted = extract_tool_pair(
        plan,
        policy=policy,
        available_search_names={"search_local"},
        allowed_purposes={"earlier_events_and_timeline"},
        call_counts={},
    )
    assert extracted.search_call.name == "search_local"
    assert extracted.collect_call.arguments.source_call_id == "search-1"


def test_strict_plan_rejects_search_without_collect_chunk() -> None:
    with pytest.raises(ValidationError):
        SupplementPlan(
            supplement_needed=True,
            coverage=_coverage(),
            next_step="use_tools",
            tool_calls=[
                SearchLocalToolCall(
                    call_id="search-1",
                    name="search_local",
                    arguments=_search_arguments(),
                )
            ],
            reason="The article lacks context.",
        )


def test_tool_extractor_rejects_unavailable_search() -> None:
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=_coverage(),
        next_step="use_tools",
        tool_calls=[
            SearchLocalToolCall(
                call_id="search-1",
                name="search_local",
                arguments=_search_arguments(),
            ),
            CollectChunkToolCall(
                call_id="collect-1",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-1", max_chunks=4
                ),
            ),
        ],
        reason="More context is needed.",
    )
    with pytest.raises(ToolCallRejected, match="unavailable"):
        extract_tool_pair(
            plan,
            policy=load_supplement_tool_policy("config/supplement_tools.yaml"),
            available_search_names=set(),
            allowed_purposes={"earlier_events_and_timeline"},
            call_counts={},
        )


def test_coverage_area_stops_at_three_distinct_relevant_chunks() -> None:
    target_gaps = {"earlier_events_and_timeline"}
    evidence_by_area = {
        name: set()
        for name in (
            "earlier_events_and_timeline",
            "affected_people_and_effects",
            "missing_information_from_other_reporting",
            "disagreement_or_uncertainty",
        )
    }
    satisfied_areas: set[str] = set()
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=SupplementCoverageAssessment(
            earlier_events_and_timeline=CoverageDecision(
                needed=True,
                reason="More timeline context could still be useful.",
                evidence_ids=[10, 11, 12],
            ),
                affected_people_and_effects=CoverageDecision(
                    needed=False, reason="Not a target area.", evidence_ids=[]
                ),
                missing_information_from_other_reporting=CoverageDecision(
                    needed=False, reason="Not a target area.", evidence_ids=[]
                ),
                disagreement_or_uncertainty=CoverageDecision(
                    needed=False, reason="Not a target area.", evidence_ids=[]
            ),
        ),
        next_step="use_tools",
        tool_calls=[
            SearchLocalToolCall(
                call_id="search-2",
                name="search_local",
                arguments=_search_arguments(),
            ),
            CollectChunkToolCall(
                call_id="collect-2",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-2", max_chunks=3
                ),
            ),
        ],
        reason="Assess the gathered timeline evidence.",
    )

    _update_coverage_ledger(
        plan,
        target_gaps=target_gaps,
        evidence_by_area=evidence_by_area,
        satisfied_areas=satisfied_areas,
        valid_evidence_ids={10, 11, 12, 99},
    )

    assert len(evidence_by_area["earlier_events_and_timeline"]) == (
        MAX_EVIDENCE_PER_COVERAGE_AREA
    )
    assert _coverage_research_complete(
        target_gaps, evidence_by_area, satisfied_areas
    )
    assert (
        _coverage_target_payload(
            target_gaps=target_gaps,
            evidence_by_area=evidence_by_area,
            satisfied_areas=satisfied_areas,
        )["earlier_events_and_timeline"]["status"]
        == "max_target_reached"
    )


def test_coverage_evidence_rejects_unknown_ids_and_can_stop_early() -> None:
    target_gaps = {"affected_people_and_effects"}
    evidence_by_area = {
        name: set()
        for name in (
            "earlier_events_and_timeline",
            "affected_people_and_effects",
            "missing_information_from_other_reporting",
            "disagreement_or_uncertainty",
        )
    }
    satisfied_areas: set[str] = set()
    coverage = _coverage()
    coverage.affected_people_and_effects = CoverageDecision(
        needed=False,
        reason="One authoritative excerpt directly identifies the affected group.",
        evidence_ids=[20, 999],
    )
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=coverage,
        next_step="compose",
        tool_calls=[],
        reason="The target is adequately supported.",
    )

    _update_coverage_ledger(
        plan,
        target_gaps=target_gaps,
        evidence_by_area=evidence_by_area,
        satisfied_areas=satisfied_areas,
        valid_evidence_ids={20},
    )

    assert evidence_by_area["affected_people_and_effects"] == {20}
    assert "affected_people_and_effects" in satisfied_areas
    assert _coverage_research_complete(
        target_gaps, evidence_by_area, satisfied_areas
    )


def test_tavily_none_depth_omits_depth_and_returns_discovery_only(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        tavily_api_key="tvly-test",
        tavily_search_depth="none",
    )
    provider = TavilySearchProvider(settings)
    captured: dict[str, object] = {}

    def fake_post(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        assert path == "search"
        return {
            "results": [
                {
                    "title": "A relevant report",
                    "url": "https://www.reuters.com/world/example",
                    "content": "A discovery snippet that is not saved as evidence.",
                    "score": 0.91,
                    "published_date": "2026-07-27T10:00:00Z",
                    "raw_content": "must not be requested",
                }
            ]
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    hits = provider.search(
        query="policy background",
        allowed_domains={"reuters.com"},
        max_results=3,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 27),
    )

    assert "search_depth" not in captured
    assert captured["include_raw_content"] is False
    assert captured["start_date"] == "2026-07-01"
    assert captured["end_date"] == "2026-07-27"
    assert hits[0].url == "https://www.reuters.com/world/example"
    assert hits[0].snippet is not None


def test_structured_search_builds_deterministic_query() -> None:
    arguments = _search_arguments()

    assert build_search_query(arguments) == (
        "Federal vehicle emissions rule background timeline vehicle emissions "
        "final rule Environmental Protection Agency"
    )


def test_structured_search_rejects_inverted_dates() -> None:
    payload = _search_arguments().model_dump()
    payload["start_date"] = date(2026, 8, 1)
    payload["end_date"] = date(2026, 7, 1)

    with pytest.raises(ValidationError, match="start_date"):
        SearchToolArguments.model_validate(payload)


def test_tool_extractor_rejects_purpose_without_active_gap() -> None:
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=_coverage(),
        next_step="use_tools",
        tool_calls=[
            SearchLocalToolCall(
                call_id="search-1",
                name="search_local",
                arguments=_search_arguments(),
            ),
            CollectChunkToolCall(
                call_id="collect-1",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-1", max_chunks=4
                ),
            ),
        ],
        reason="More context is needed.",
    )

    with pytest.raises(ToolCallRejected, match="coverage gap"):
        extract_tool_pair(
            plan,
            policy=load_supplement_tool_policy("config/supplement_tools.yaml"),
            available_search_names={"search_local"},
            allowed_purposes={"affected_people_and_effects"},
            call_counts={},
        )


def test_web_search_domains_are_policy_bounded_and_result_count_is_capped() -> None:
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=_coverage(),
        next_step="use_tools",
        tool_calls=[
            WebSearchToolCall(
                call_id="search-1",
                name="web_search",
                arguments=_search_arguments(preferred_domains=["reuters.com"]),
            ),
            CollectChunkToolCall(
                call_id="collect-1",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-1", max_chunks=8
                ),
            ),
        ],
        reason="External reporting may provide the missing context.",
    )
    extracted = extract_tool_pair(
        plan,
        policy=load_supplement_tool_policy("config/supplement_tools.yaml"),
        available_search_names={"web_search"},
        allowed_purposes={"earlier_events_and_timeline"},
        call_counts={},
    )

    assert extracted.allowed_domains == frozenset({"reuters.com"})
    assert extracted.result_limit == 3


def test_web_search_rejects_domain_outside_yaml_policy() -> None:
    plan = SupplementPlan(
        supplement_needed=True,
        coverage=_coverage(),
        next_step="use_tools",
        tool_calls=[
            WebSearchToolCall(
                call_id="search-1",
                name="web_search",
                arguments=_search_arguments(preferred_domains=["example.com"]),
            ),
            CollectChunkToolCall(
                call_id="collect-1",
                name="collect_chunk",
                arguments=CollectChunkArguments(
                    source_call_id="search-1", max_chunks=3
                ),
            ),
        ],
        reason="External reporting may provide the missing context.",
    )

    with pytest.raises(ToolCallRejected, match="outside policy"):
        extract_tool_pair(
            plan,
            policy=load_supplement_tool_policy("config/supplement_tools.yaml"),
            available_search_names={"web_search"},
            allowed_purposes={"earlier_events_and_timeline"},
            call_counts={},
        )


def test_verification_requires_exact_types_and_all_fields() -> None:
    with pytest.raises(ValidationError):
        SupplementStatementVerification.model_validate(
            {
                "card_index": 0,
                "statement_index": 0,
                "supported": "true",
                "evidence_ids": [10],
                "reason": "Supported.",
            }
        )
    with pytest.raises(ValidationError):
        SupplementStatementVerification.model_validate(
            {
                "card_index": 0,
                "statement_index": 0,
                "supported": True,
                "reason": "Missing evidence_ids.",
            }
        )


def test_verification_contract_requires_one_result_per_draft_statement() -> None:
    verification = SupplementVerification(
        statements=[
            SupplementStatementVerification(
                card_index=0,
                statement_index=0,
                supported=True,
                evidence_ids=[10],
                reason="The excerpt directly supports the estimate.",
            ),
            SupplementStatementVerification(
                card_index=0,
                statement_index=1,
                supported=False,
                evidence_ids=[],
                reason="The causal claim is unsupported.",
            ),
        ]
    )
    validate_verification_contract(
        _draft(), verification, valid_evidence_ids={10, 11}
    )

    with pytest.raises(VerificationContractError, match="missing"):
        validate_verification_contract(
            _draft(), SupplementVerification(statements=[]), valid_evidence_ids={10, 11}
        )


def test_structured_client_exposes_exact_validation_error(monkeypatch) -> None:
    client = OpenAICompatibleClient(
        api_key="test-key", base_url="https://provider.invalid", timeout_seconds=1
    )
    malformed = (
        '{"statements":[{"card_index":0,"statement_index":0,'
        '"supported":"true","evidence_ids":[10],"reason":"Supported."}]}'
    )
    monkeypatch.setattr(
        client,
        "_post",
        lambda _path, _payload: (
            {"choices": [{"message": {"content": malformed}}]},
            1.0,
        ),
    )

    with pytest.raises(StructuredOutputError) as captured:
        client.structured_chat(
            model="test-model",
            system_prompt="Verify.",
            user_prompt="{}",
            output_model=SupplementVerification,
            max_tokens=100,
            thinking=False,
            strict_schema=False,
        )

    assert "supported" in captured.value.validation_error
    assert '"supported":"true"' in captured.value.response_preview
