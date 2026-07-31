from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import score_article_ids


def personalize_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    target_count = max(1, state.get("target_article_count", 1))
    target_article_minutes = state.get(
        "target_article_reading_minutes",
        max(1, state.get("target_reading_minutes", 1) // target_count),
    )
    scores = score_article_ids(
        session,
        state.get("eligible_article_ids", []),
        state["user_id"],
        settings,
        target_article_reading_minutes=target_article_minutes,
    )
    return {
        "candidate_scores": scores,
        "stats": {**state.get("stats", {}), "scored_candidates": len(scores)},
    }
