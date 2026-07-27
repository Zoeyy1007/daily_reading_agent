from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import embed_chunks


def embed_chunks_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    count = embed_chunks(
        session,
        state.get("evidence_cluster_ids", []),
        run_id=state["run_id"],
        settings=settings,
    )
    return {"stats": {**state.get("stats", {}), "chunks_embedded": count}}
