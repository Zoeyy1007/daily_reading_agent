from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.phase_five_service import cluster_articles


def cluster_stories_node(
    state: DailyRunState, session: Session, settings: Settings
) -> dict[str, object]:
    if not settings.phase_five_enabled:
        return {"story_cluster_ids": [], "evidence_cluster_ids": []}
    cluster_ids, evidence_cluster_ids = cluster_articles(
        session, state.get("eligible_article_ids", []), settings=settings
    )
    return {
        "story_cluster_ids": cluster_ids,
        "evidence_cluster_ids": evidence_cluster_ids,
        "stats": {
            **state.get("stats", {}),
            "story_clusters": len(cluster_ids),
            "evidence_clusters": len(evidence_cluster_ids),
        },
    }
