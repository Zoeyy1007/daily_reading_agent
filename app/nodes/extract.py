from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.ingestion_service import extract_articles


def extract_node(
    state: DailyRunState, session: Session, _settings: Settings
) -> dict[str, object]:
    extracted, failed = extract_articles(
        session, state.get("candidate_article_ids", [])
    )
    return {
        "stats": {
            **state.get("stats", {}),
            "extracted": extracted,
            "extraction_failed": failed,
        }
    }
