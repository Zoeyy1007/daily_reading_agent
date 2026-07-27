from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import compare_cluster_evidence


def compare_evidence_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {}
    count = compare_cluster_evidence(
        session,
        state.get("evidence_cluster_ids", []),
        run_id=state["run_id"],
        settings=settings,
    )
    return {"stats": {**state.get("stats", {}), "clusters_compared": count}}
