from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import select_scored_articles


def select_node(
    state: DailyRunState, _session: Session, _settings: Settings
) -> dict[str, object]:
    selected = select_scored_articles(
        state.get("candidate_scores", []),
        state["target_article_count"],
        state["target_reading_minutes"],
    )
    return {
        "selected_scores": selected,
        "selected_article_ids": [item["article_id"] for item in selected],
        "stats": {**state.get("stats", {}), "selected_candidates": len(selected)},
    }
