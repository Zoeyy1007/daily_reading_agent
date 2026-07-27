from datetime import date

from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import persist_agent_reading_list
from app.services.phase_five_service import (
    cleanup_expired_evidence,
    extend_selected_evidence_retention,
)


def finalize_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    reading_list = persist_agent_reading_list(
        session,
        user_id=state["user_id"],
        list_date=date.fromisoformat(state["list_date"]),
        selected=state.get("selected_scores", []),
        settings=settings,
        regenerate=state.get("regenerate", False),
    )
    deleted_evidence = 0
    if settings.phase_five_enabled:
        extend_selected_evidence_retention(
            session,
            state.get("selected_article_ids", []),
            settings=settings,
        )
        deleted_evidence = cleanup_expired_evidence(session)
    return {
        "reading_list_id": reading_list.id,
        "status": "complete",
        "stats": {
            **state.get("stats", {}),
            "final_article_count": reading_list.actual_article_count,
            "final_reading_minutes": reading_list.actual_reading_minutes,
            "expired_evidence_deleted": deleted_evidence,
        },
    }
