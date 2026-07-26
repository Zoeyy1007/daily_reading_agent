from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    canonical_url: str
    title: str
    rss_summary: str | None
    author: str | None
    published_at: datetime | None
    fetched_at: datetime | None
    word_count: int | None
    language: str | None
    content_type: str | None
    status: str
    extractor_used: str | None
    extraction_error: str | None


class ArticleDetail(ArticleRead):
    content_text: str | None
