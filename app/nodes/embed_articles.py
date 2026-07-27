from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import embed_articles


def embed_articles_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    count = embed_articles(
        session,
        state.get("eligible_article_ids", []),
        run_id=state["run_id"],
        settings=settings,
    )
    return {"stats": {**state.get("stats", {}), "articles_embedded": count}}
