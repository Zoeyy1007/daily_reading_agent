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
    database_url: str = (
        "postgresql+psycopg://daily_reading:daily_reading@127.0.0.1:5432/daily_reading"
    )
    rss_poll_minutes: int = Field(default=30, ge=1)
    http_timeout_seconds: float = Field(default=20, gt=0)
    article_min_words: int = Field(default=150, ge=1)
    user_agent: str = "DailyReadingAgent/0.1 (personal local project)"
    jina_api_key: str | None = None
    scheduler_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
