from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UsageEventCreate(BaseModel):
    visitor_id: UUID
    event_type: Literal["page_view"]
    path: str = Field(min_length=1, max_length=120)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/") or "?" in normalized or "#" in normalized:
            raise ValueError("path must be a normalized route without query parameters")
        return normalized


class UsageEventReceipt(BaseModel):
    recorded: bool


class DailyUsageRead(BaseModel):
    day: date
    page_views: int
    unique_visitors: int
    signed_in_users: int


class UsageSummaryRead(BaseModel):
    days: int
    total_page_views: int
    unique_visitors: int
    signed_in_users: int
    daily: list[DailyUsageRead]
