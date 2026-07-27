from sqlalchemy.orm import Session

from app.agent.state import DailyRunState
from app.config import Settings
from app.services.agent_stage_service import all_extracted_article_ids


def expand_sources_node(
    state: DailyRunState, session: Session, _settings: Settings
) -> dict[str, object]:
    expansion_round = state.get("expansion_round", 0) + 1
    candidate_ids = state.get("candidate_article_ids", [])
    stats = dict(state.get("stats", {}))
    if expansion_round == 1:
        existing_ids = all_extracted_article_ids(session)
        candidate_ids = sorted(set(candidate_ids) | set(existing_ids))
        stats["round_1_database_candidates"] = len(existing_ids)
    elif expansion_round == 2:
        # Phase 6 will plug a related-coverage search provider into this role.
        # Until then the absence is explicit, recorded, and non-fatal.
        stats["round_2_related_search"] = "provider_not_configured"
    else:
        # Current hard filters are never relaxed. There is no separate soft
        # eligibility threshold yet, so this round keeps the best known pool.
        stats["round_3_soft_preferences"] = "no_soft_filter_configured"
    return {
        "expansion_round": expansion_round,
        "candidate_article_ids": candidate_ids,
        "stats": stats,
    }
