from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Daily Reading"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+psycopg://daily_reading:daily_reading@127.0.0.1:5432/daily_reading"
    )
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=7200)
    rss_poll_minutes: int = Field(default=30, ge=1)
    http_timeout_seconds: float = Field(default=20, gt=0)
    article_min_words: int = Field(default=150, ge=1)
    user_agent: str = "DailyReadingAgent/0.1 (personal local project)"
    jina_api_key: str | None = None
    ingestion_max_concurrency: int = Field(default=4, ge=1, le=16)
    scheduler_enabled: bool = False
    default_user_id: int = Field(default=1, ge=1)
    auth_cookie_name: str = "daily_reading_session"
    auth_cookie_secure: bool = False
    auth_session_days: int = Field(default=30, ge=1, le=365)
    analytics_enabled: bool = True
    analytics_admin_login_ids: str = "18"
    analytics_retention_days: int = Field(default=365, ge=30, le=3650)

    # Phase 2 filtering and selection settings
    min_article_words: int = Field(default=200, ge=1)
    max_article_words: int = Field(default=4000, ge=1)
    max_article_age_hours: int = Field(default=48, ge=1)
    allowed_languages: str = "en"
    allowed_content_types: str = "news,analysis,opinion,tutorial,other"
    preferred_topics: str = ""
    preferred_source_ids: str = ""
    blocked_source_ids: str = ""
    daily_article_target: int = Field(default=5, ge=1, le=10)
    expected_reading_minutes_per_article: int = Field(default=6, ge=2, le=25)
    daily_reading_minutes: int = Field(default=30, ge=1)
    reading_words_per_minute: int = Field(default=225, ge=1)
    daily_list_hour: int = Field(default=8, ge=0, le=23)
    scheduler_timezone: str = "America/Los_Angeles"
    personalization_weight: float = Field(default=30.0, ge=0, le=100)

    # Phase 4 agent workflow settings
    agent_max_expansion_rounds: int = Field(default=3, ge=0, le=10)
    agent_recursion_limit: int = Field(default=40, ge=10, le=200)
    agent_run_in_background: bool = True

    # Phase 5 provider roles. Each role is deliberately independent.
    phase_five_enabled: bool = True
    phase_five_max_articles: int = Field(default=30, ge=1, le=100)
    llm_max_concurrency: int = Field(default=3, ge=1, le=16)
    embedding_max_concurrency: int = Field(default=2, ge=1, le=8)

    embedding_provider: str = "qwen"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = Field(default=1024, ge=64, le=2000)
    embedding_batch_size: int = Field(default=10, ge=1, le=10)
    dashscope_api_key: SecretStr | None = None
    qwen_base_url: str = ""

    classification_provider: str = "deepseek"
    classification_model: str = "deepseek-v4-flash"
    classification_thinking: bool = False
    classification_max_output_tokens: int = Field(default=1500, ge=100)

    claim_extraction_provider: str = "deepseek"
    claim_extraction_model: str = "deepseek-v4-pro"
    claim_extraction_thinking: bool = False
    claim_extraction_max_output_tokens: int = Field(default=8000, ge=500)
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    evidence_comparison_provider: str = "deepseek"
    evidence_comparison_model: str = "deepseek-v4-pro"
    evidence_comparison_thinking: bool = False
    evidence_comparison_max_output_tokens: int = Field(default=4000, ge=500)
    moonshot_api_key: SecretStr | None = None
    kimi_base_url: str = "https://api.moonshot.cn/v1"

    article_chunk_word_threshold: int = Field(default=1500, ge=500)
    article_chunk_target_words: int = Field(default=800, ge=200)
    article_chunk_overlap_words: int = Field(default=100, ge=0)
    evidence_retrieval_chunk_limit: int = Field(default=20, ge=5, le=50)
    evidence_bm25_weight: float = Field(default=0.4, ge=0, le=1)
    evidence_vector_weight: float = Field(default=0.6, ge=0, le=1)
    evidence_max_claim_pairs: int = Field(default=20, ge=1, le=100)
    evidence_pair_batch_size: int = Field(default=5, ge=1, le=20)
    story_cluster_similarity_threshold: float = Field(default=0.82, ge=0, le=1)
    story_cluster_redundancy_threshold: float = Field(default=0.94, ge=0, le=1)
    story_cluster_max_articles: int = Field(default=5, ge=2, le=20)
    story_cluster_lookback_days: int = Field(default=7, ge=1, le=30)
    prompt_version: str = "phase5-v2"

    unselected_chunk_retention_days: int = Field(default=7, ge=1, le=30)
    unselected_evidence_retention_days: int = Field(default=7, ge=1, le=30)
    selected_evidence_retention_days: int = Field(default=30, ge=1, le=30)
    cluster_metadata_retention_days: int = Field(default=30, ge=1, le=90)
    model_call_log_retention_days: int = Field(default=30, ge=1, le=90)

    # Phase 6 source-grounded supplemental information
    phase_six_enabled: bool = False
    supplement_model: str = "deepseek-v4-pro"
    supplement_thinking: bool = False
    supplement_max_output_tokens: int = Field(default=4000, ge=500)
    supplement_max_iterations: int = Field(default=4, ge=1, le=10)
    supplement_max_concurrency: int = Field(default=2, ge=1, le=8)
    supplement_verification_max_attempts: int = Field(default=3, ge=1, le=5)
    supplement_word_ratio: float = Field(default=0.5, gt=0, le=0.5)
    supplement_retention_days: int = Field(default=30, ge=1, le=30)
    supplement_tool_policy_path: str = "config/supplement_tools.yaml"
    tavily_api_key: SecretStr | None = None
    tavily_base_url: str = "https://api.tavily.com"
    tavily_search_depth: str = "none"

    @field_validator("tavily_search_depth")
    @classmethod
    def validate_tavily_search_depth(cls, value: str) -> str:
        normalized = value.strip().casefold()
        allowed = {"none", "basic", "advanced", "fast", "ultra-fast"}
        if normalized not in allowed:
            raise ValueError(
                "TAVILY_SEARCH_DEPTH must be none, basic, advanced, fast, or ultra-fast"
            )
        return normalized

    @staticmethod
    def _string_set(value: str) -> set[str]:
        return {item.strip().casefold() for item in value.split(",") if item.strip()}

    @staticmethod
    def _integer_set(value: str) -> set[int]:
        return {int(item.strip()) for item in value.split(",") if item.strip()}

    @property
    def allowed_language_set(self) -> set[str]:
        return self._string_set(self.allowed_languages)

    @property
    def allowed_content_type_set(self) -> set[str]:
        return self._string_set(self.allowed_content_types)

    @property
    def analytics_admin_login_id_set(self) -> set[str]:
        return self._string_set(self.analytics_admin_login_ids)

    @property
    def preferred_topic_set(self) -> set[str]:
        return self._string_set(self.preferred_topics)

    @property
    def preferred_source_id_set(self) -> set[int]:
        return self._integer_set(self.preferred_source_ids)

    @property
    def blocked_source_id_set(self) -> set[int]:
        return self._integer_set(self.blocked_source_ids)

    @property
    def resolved_database_url(self) -> str:
        """Normalize hosted PostgreSQL URLs to the installed psycopg v3 driver."""
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgres://")
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return url.replace("@localhost:", "@127.0.0.1:")

    @property
    def resolved_tavily_search_depth(self) -> str | None:
        """`none` is an app sentinel meaning that Tavily should use its default."""
        return None if self.tavily_search_depth == "none" else self.tavily_search_depth


@lru_cache
def get_settings() -> Settings:
    return Settings()
