from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_range(self) -> "ChatFilters":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("Chat date ranges cannot exceed 366 days")
        return self


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    id: int
    request_id: str
    role: Literal["user", "assistant"]
    content: str
    metadata_json: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebSocketMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["message"]
    request_id: UUID
    content: str = Field(min_length=1, max_length=4000)
    filters: ChatFilters


class WebSocketEvent(BaseModel):
    type: Literal["assistant.delta", "assistant.done", "error"]
    request_id: str
    content: str | None = None
    code: str | None = None
    message: str | None = None
