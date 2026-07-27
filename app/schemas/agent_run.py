from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentRunCreate(BaseModel):
    list_date: date | None = None
    regenerate: bool = True
    background: bool | None = None
    max_expansion_rounds: int | None = Field(default=None, ge=0, le=10)


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_name: str
    attempt: int
    status: str
    elapsed_ms: float | None
    message: str | None
    started_at: datetime
    completed_at: datetime | None


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: str
    user_id: int
    list_date: date
    status: str
    current_node: str | None
    expansion_round: int
    max_expansion_rounds: int
    selected_count: int
    reading_list_id: int | None
    last_error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    events: list[RunEventRead] = Field(default_factory=list)
