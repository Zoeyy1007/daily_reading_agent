from collections.abc import Mapping
from dataclasses import dataclass

from app.agent.tool_policy import SupplementToolPolicy, ToolPolicy
from app.ai.schemas import (
    CollectChunkToolCall,
    MCPGovernmentSearchToolCall,
    WebSearchToolCall,
    SearchLocalToolCall,
    SupplementPlan,
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


def extract_tool_pair(
    plan: SupplementPlan,
    *,
    policy: SupplementToolPolicy,
    available_search_names: set[str],
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

    return ExtractedToolPair(
        search_call=search_call,
        collect_call=collect_call,
        search_policy=search_policy,
        collect_policy=collect_policy,
    )
