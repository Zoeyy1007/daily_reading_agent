from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import apply_representative_selection


def apply_evidence_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    eligible = apply_representative_selection(
        session,
        state.get("eligible_article_ids", []),
        state.get("story_cluster_ids", []),
    )
    return {
        "eligible_article_ids": eligible,
        "stats": {
            **state.get("stats", {}),
            "post_evidence_candidates": len(eligible),
        },
    }
