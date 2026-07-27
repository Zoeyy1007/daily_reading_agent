from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import chunk_cluster_articles


def chunk_articles_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    count = chunk_cluster_articles(
        session, state.get("evidence_cluster_ids", []), settings=settings
    )
    return {"stats": {**state.get("stats", {}), "chunks_created": count}}
