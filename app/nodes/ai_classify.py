from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import classify_articles_with_model


def ai_classify_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    count = classify_articles_with_model(
        session,
        state.get("eligible_article_ids", []),
        run_id=state["run_id"],
        settings=settings,
    )
    return {"stats": {**state.get("stats", {}), "ai_classified": count}}
