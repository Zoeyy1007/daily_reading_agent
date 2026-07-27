from functools import lru_cache

from pydantic import Field
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
    rss_poll_minutes: int = Field(default=30, ge=1)
    http_timeout_seconds: float = Field(default=20, gt=0)
    article_min_words: int = Field(default=150, ge=1)
    user_agent: str = "DailyReadingAgent/0.1 (personal local project)"
    jina_api_key: str | None = None
    scheduler_enabled: bool = False
    default_user_id: int = Field(default=1, ge=1)

    # Phase 2 filtering and selection settings
    min_article_words: int = Field(default=200, ge=1)
    max_article_words: int = Field(default=4000, ge=1)
    max_article_age_hours: int = Field(default=48, ge=1)
    allowed_languages: str = "en"
    allowed_content_types: str = "news,analysis,opinion,tutorial,other"
    preferred_topics: str = ""
    preferred_source_ids: str = ""
    blocked_source_ids: str = ""
    daily_article_target: int = Field(default=5, ge=1)
    daily_reading_minutes: int = Field(default=30, ge=1)
    reading_words_per_minute: int = Field(default=225, ge=1)
    daily_list_hour: int = Field(default=7, ge=0, le=23)
    scheduler_timezone: str = "America/Los_Angeles"
    personalization_weight: float = Field(default=30.0, ge=0, le=100)

    # Phase 4 agent workflow settings
    agent_max_expansion_rounds: int = Field(default=3, ge=0, le=10)
    agent_recursion_limit: int = Field(default=40, ge=10, le=200)
    agent_run_in_background: bool = True

    # Model roles are intentionally independent. Provider clients are added when
    # an AI-powered node is introduced; the Phase 4 graph itself needs no API key.
    classification_model: str | None = None
    embedding_model: str | None = None
    claim_extraction_model: str | None = None
    evidence_comparison_model: str | None = None

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
        """Prefer Docker's IPv4 host binding when a local URL says localhost."""
        return self.database_url.replace("@localhost:", "@127.0.0.1:")


@lru_cache
def get_settings() -> Settings:
    return Settings()
