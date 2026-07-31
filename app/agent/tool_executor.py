from collections.abc import Mapping
from dataclasses import dataclass

from app.agent.tool_policy import SupplementToolPolicy, ToolPolicy
from app.ai.schemas import (
    CollectChunkToolCall,
    MCPGovernmentSearchToolCall,
    SearchLocalToolCall,
    SearchToolArguments,
    SupplementPlan,
    WebSearchToolCall,
)

SearchCall = SearchLocalToolCall | WebSearchToolCall | MCPGovernmentSearchToolCall


class ToolCallRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractedToolPair:
    search_call: SearchCall
    collect_call: CollectChunkToolCall
    search_policy: ToolPolicy
    collect_policy: ToolPolicy
    query: str
    allowed_domains: frozenset[str]
    result_limit: int


PURPOSE_QUERY_HINTS = {
    "earlier_events_and_timeline": "background timeline",
    "affected_people_and_effects": "affected people impact",
    "missing_information_from_other_reporting": "additional reporting details",
    "disagreement_or_uncertainty": "disagreement uncertainty",
}


def build_search_query(arguments: SearchToolArguments) -> str:
    """Build a bounded provider query from validated structured fields."""
    values = [
        arguments.event,
        PURPOSE_QUERY_HINTS[arguments.purpose],
        *arguments.keywords,
        *arguments.entities,
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if key in seen:
            continue
        candidate = " ".join([*unique, normalized])
        if len(candidate) > 500:
            break
        unique.append(normalized)
        seen.add(key)
    return " ".join(unique)


def _domain_is_allowed(domain: str, allowed_domains: set[str]) -> bool:
    return any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in allowed_domains
    )


def extract_tool_pair(
    plan: SupplementPlan,
    *,
    policy: SupplementToolPolicy,
    available_search_names: set[str],
    allowed_purposes: set[str],
    call_counts: Mapping[str, int],
) -> ExtractedToolPair:
    """Convert validated LLM output into an authorized, bounded tool pair."""
    if plan.next_step != "use_tools" or len(plan.tool_calls) != 2:
        raise ToolCallRejected("Plan does not contain a two-call tool step")
    search_call, collect_call = plan.tool_calls
    if search_call.name == "collect_chunk" or collect_call.name != "collect_chunk":
        raise ToolCallRejected("Expected search followed by collect_chunk")
    if search_call.name not in available_search_names:
        raise ToolCallRejected("Search tool is unavailable")
    if search_call.arguments.purpose not in allowed_purposes:
        raise ToolCallRejected("Search purpose is not an unresolved coverage gap")

    search_policy = policy.tool(search_call.name)
    collect_policy = policy.tool("collect_chunk")
    if not search_policy.enabled or not search_policy.agent_callable:
        raise ToolCallRejected("Search tool is disabled by policy")
    if not collect_policy.enabled or not collect_policy.agent_callable:
        raise ToolCallRejected("collect_chunk is disabled by policy")
    if call_counts.get(search_call.name, 0) >= search_policy.max_calls_per_article:
        raise ToolCallRejected("Search tool call limit reached")
    if call_counts.get("collect_chunk", 0) >= collect_policy.max_calls_per_article:
        raise ToolCallRejected("collect_chunk call limit reached")
    if collect_call.arguments.max_chunks > collect_policy.max_results:
        raise ToolCallRejected("collect_chunk requested too many chunks")

    requested_domains = set(search_call.arguments.preferred_domains)
    policy_domains = search_policy.permissions.allowed_domain_set
    if search_call.name == "search_local" and requested_domains:
        raise ToolCallRejected("Local search cannot request external domains")
    rejected_domains = {
        domain
        for domain in requested_domains
        if not _domain_is_allowed(domain, policy_domains)
    }
    if rejected_domains:
        raise ToolCallRejected(
            f"Search requested domains outside policy: {sorted(rejected_domains)}"
        )
    allowed_domains = requested_domains or policy_domains
    result_limit = min(
        search_call.arguments.max_results,
        search_policy.max_results,
        collect_policy.max_results,
        collect_call.arguments.max_chunks,
    )

    return ExtractedToolPair(
        search_call=search_call,
        collect_call=collect_call,
        search_policy=search_policy,
        collect_policy=collect_policy,
        query=build_search_query(search_call.arguments),
        allowed_domains=frozenset(allowed_domains),
        result_limit=result_limit,
    )
