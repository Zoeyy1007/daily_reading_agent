from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import (
    cleanup_expired_evidence,
    extend_selected_evidence_retention,
)


def finalize_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    deleted_evidence = 0
    if settings.phase_five_enabled:
        extend_selected_evidence_retention(
            session,
            state.get("selected_article_ids", []),
            settings=settings,
        )
        deleted_evidence = cleanup_expired_evidence(session)
    return {
        "reading_list_id": state.get("reading_list_id"),
        "status": "complete",
        "stats": {
            **state.get("stats", {}),
            "expired_evidence_deleted": deleted_evidence,
        },
    }
