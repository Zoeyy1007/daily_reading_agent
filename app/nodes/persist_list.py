from datetime import date

from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import persist_agent_reading_list


def persist_list_node(
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
    return {
        "reading_list_id": reading_list.id,
        "stats": {
            **state.get("stats", {}),
            "final_article_count": reading_list.actual_article_count,
            "final_reading_minutes": reading_list.actual_reading_minutes,
        },
    }
