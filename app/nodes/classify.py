from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import classify_article_ids


def classify_node(
    state: DailyRunState, session: Session, _settings: Settings
) -> dict[str, object]:
    count = classify_article_ids(session, state.get("candidate_article_ids", []))
    return {
        "stats": {**state.get("stats", {}), "classified_candidates": count}
    }
