from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.ingestion_service import discover_all_enabled_sources


def collect_node(
    state: DailyRunState, session: Session, _settings: Settings
) -> dict[str, object]:
    results = discover_all_enabled_sources(session)
    article_ids = [article_id for result in results for article_id in result.article_ids]
    return {
        "candidate_article_ids": sorted(set(article_ids)),
        "stats": {
            **state.get("stats", {}),
            "sources_polled": len(results),
            "discovered": sum(result.discovered for result in results),
            "exact_duplicates": sum(result.duplicates for result in results),
            "not_modified_sources": sum(result.not_modified for result in results),
            "source_failures": sum(result.error is not None for result in results),
        },
    }
