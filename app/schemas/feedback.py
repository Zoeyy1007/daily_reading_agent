from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import FeedbackEventType, FeedbackReason
from app.schemas.article import ArticleRead


class FeedbackCreate(BaseModel):
    event_type: FeedbackEventType
    reason: FeedbackReason | None = None


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    article_id: int
    event_type: str
    reason: str | None
    created_at: datetime


class SavedArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    saved_at: datetime
    article: ArticleRead


class PreferenceFeatureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    feature_type: str
    feature_value: str
    score: float
    confidence: float
    positive_count: int
    negative_count: int
    updated_at: datetime
