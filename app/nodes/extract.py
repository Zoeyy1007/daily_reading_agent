from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.ingestion_service import extract_articles_async


async def extract_node(
    state: DailyRunState, _session: Session, settings: Settings
) -> dict[str, object]:
    extracted, failed = await extract_articles_async(
        state.get("candidate_article_ids", []),
        max_concurrency=settings.ingestion_max_concurrency,
    )
    return {
        "stats": {
            **state.get("stats", {}),
            "extracted": extracted,
            "extraction_failed": failed,
        }
    }
