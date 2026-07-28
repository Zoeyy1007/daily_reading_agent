from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.supplement_service import generate_supplements_for_list


def supplement_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    reading_list_id = state.get("reading_list_id")
    if not settings.phase_six_enabled or reading_list_id is None:
        return {
            "stats": {
                **state.get("stats", {}),
                "supplements": "disabled" if not settings.phase_six_enabled else "no_list",
            }
        }
    result = generate_supplements_for_list(
        session,
        reading_list_id,
        daily_run_id=state["run_id"],
        settings=settings,
    )
    return {
        "stats": {
            **state.get("stats", {}),
            "supplements_complete": result.complete,
            "supplements_skipped": result.skipped,
            "supplements_insufficient": result.insufficient,
            "supplements_failed": result.failed,
            "supplement_evidence_items": result.evidence_items,
            "supplement_cards": result.cards,
        }
    }
