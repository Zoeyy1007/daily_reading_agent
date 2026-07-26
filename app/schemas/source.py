from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    feed_url: HttpUrl
    site_url: HttpUrl | None = None
    enabled: bool = True
    poll_interval_minutes: int = Field(default=30, ge=1)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    site_url: HttpUrl | None = None
    enabled: bool | None = None
    poll_interval_minutes: int | None = Field(default=None, ge=1)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    feed_url: str
    site_url: str | None
    enabled: bool
    poll_interval_minutes: int
    last_polled_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IngestionResult(BaseModel):
    source_id: int
    discovered: int = 0
    extracted: int = 0
    failed: int = 0
    duplicates: int = 0
    not_modified: bool = False
