from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import filter_article_ids


def filter_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    eligible, rejection_counts = filter_article_ids(
        session, state.get("candidate_article_ids", []), settings
    )
    rejection_summary = ",".join(
        f"{reason}:{count}" for reason, count in sorted(rejection_counts.items())
    )
    return {
        "eligible_article_ids": eligible,
        "stats": {
            **state.get("stats", {}),
            "eligible_candidates": len(eligible),
            "filter_rejections": rejection_summary,
        },
    }
