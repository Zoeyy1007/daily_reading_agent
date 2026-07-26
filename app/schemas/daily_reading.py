from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.article import ArticleRead


class DailyReadingGenerate(BaseModel):
    list_date: date | None = None
    regenerate: bool = False


class DailyReadingItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    total_score: float
    freshness_score: float
    topic_score: float
    source_score: float
    length_score: float
    reading_minutes: int
    selection_reason: str
    article: ArticleRead


class DailyReadingListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_date: date
    target_article_count: int
    target_reading_minutes: int
    actual_article_count: int
    actual_reading_minutes: int
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[DailyReadingItemRead]
