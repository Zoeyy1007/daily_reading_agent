from typing import TypedDict


class CandidateScore(TypedDict):
    article_id: int
    total_score: float
    base_score: float
    personalization_score: float
    freshness_score: float
    topic_score: float
    source_score: float
    length_score: float
    reading_minutes: int
    selection_reason: str


class DailyRunState(TypedDict, total=False):
    run_id: int
    thread_id: str
    user_id: int
    list_date: str
    regenerate: bool
    target_article_count: int
    target_article_reading_minutes: int
    target_reading_minutes: int
    expansion_round: int
    max_expansion_rounds: int
    candidate_article_ids: list[int]
    eligible_article_ids: list[int]
    selected_article_ids: list[int]
    story_cluster_ids: list[int]
    evidence_cluster_ids: list[int]
    candidate_scores: list[CandidateScore]
    selected_scores: list[CandidateScore]
    stats: dict[str, int | str | bool]
    errors: list[str]
    reading_list_id: int | None
    status: str
