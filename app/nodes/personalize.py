from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import score_article_ids


def personalize_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    scores = score_article_ids(
        session,
        state.get("eligible_article_ids", []),
        state["user_id"],
        settings,
    )
    return {
        "candidate_scores": scores,
        "stats": {**state.get("stats", {}), "scored_candidates": len(scores)},
    }
