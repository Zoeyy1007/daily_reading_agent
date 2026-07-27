from typing import Literal

from app.agent.state import DailyRunState


def route_after_select(
    state: DailyRunState,
) -> Literal["finalize", "expand_sources"]:
    selected_count = len(state.get("selected_article_ids", []))
    target_count = state.get("target_article_count", 0)
    expansion_round = state.get("expansion_round", 0)
    max_rounds = state.get("max_expansion_rounds", 0)
    if selected_count >= target_count or expansion_round >= max_rounds:
        return "finalize"
    return "expand_sources"
