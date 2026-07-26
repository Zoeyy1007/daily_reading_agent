from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    feed_url: HttpUrl
    publisher_id: int | None = Field(default=None, ge=1)
    category: str | None = Field(default=None, max_length=100)
    # Legacy convenience: when publisher_id is omitted, this creates or reuses
    # a publisher. New callers should create a publisher first.
    site_url: HttpUrl | None = None
    enabled: bool = True
    poll_interval_minutes: int = Field(default=30, ge=1)


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    publisher_id: int | None = Field(default=None, ge=1)
    category: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    poll_interval_minutes: int | None = Field(default=None, ge=1)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    publisher_id: int
    name: str
    category: str | None
    feed_url: str
    enabled: bool
    poll_interval_minutes: int
    last_polled_at: datetime | None
    last_success_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PublisherCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    site_url: HttpUrl | None = None
    enabled: bool = True


class PublisherUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    site_url: HttpUrl | None = None
    enabled: bool | None = None


class PublisherFeedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    feed_url: HttpUrl
    enabled: bool = True
    poll_interval_minutes: int = Field(default=30, ge=1)


class PublisherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    site_url: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PublisherDetail(PublisherRead):
    sources: list[SourceRead]


class IngestionResult(BaseModel):
    source_id: int
    discovered: int = 0
    extracted: int = 0
    failed: int = 0
    duplicates: int = 0
    not_modified: bool = False
