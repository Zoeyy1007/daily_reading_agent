from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.ingestion_service import deduplicate_article_content


def content_deduplicate_node(
    state: DailyRunState, session: Session, _settings: Settings
) -> dict[str, object]:
    kept, duplicate_count = deduplicate_article_content(
        session, state.get("candidate_article_ids", [])
    )
    return {
        "candidate_article_ids": kept,
        "stats": {
            **state.get("stats", {}),
            "content_duplicates": duplicate_count,
            "content_unique_candidates": len(kept),
        },
    }
