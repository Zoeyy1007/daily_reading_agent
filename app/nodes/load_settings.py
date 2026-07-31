from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.db.models import User


def load_settings_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    user = session.get(User, state["user_id"])
    if user is None:
        raise LookupError(f"User {state['user_id']} does not exist")
    target_count = user.daily_list_length
    target_article_minutes = user.expected_reading_minutes_per_article
    return {
        "target_article_count": target_count,
        "target_article_reading_minutes": target_article_minutes,
        "target_reading_minutes": target_count * target_article_minutes,
        "max_expansion_rounds": state.get(
            "max_expansion_rounds", settings.agent_max_expansion_rounds
        ),
        "expansion_round": state.get("expansion_round", 0),
        "candidate_article_ids": state.get("candidate_article_ids", []),
        "eligible_article_ids": state.get("eligible_article_ids", []),
        "selected_article_ids": state.get("selected_article_ids", []),
        "stats": {
            **state.get("stats", {}),
            "loaded_at": datetime.now(UTC).isoformat(),
        },
        "errors": state.get("errors", []),
        "status": "running",
    }
