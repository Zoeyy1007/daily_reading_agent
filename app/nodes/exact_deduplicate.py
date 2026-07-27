from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings


def exact_deduplicate_node(
    state: DailyRunState, _session: Session, _settings: Settings
) -> dict[str, object]:
    # URL/GUID duplicates are rejected atomically during discovery. This node
    # exposes that boundary and leaves only newly inserted IDs in graph state.
    unique_ids = sorted(set(state.get("candidate_article_ids", [])))
    return {
        "candidate_article_ids": unique_ids,
        "stats": {
            **state.get("stats", {}),
            "exact_unique_candidates": len(unique_ids),
        },
    }
