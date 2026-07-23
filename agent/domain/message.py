from pydantic import BaseModel, Field
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    TEXT = "text"
    OBJECT = "object"


class MessageObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class UserMessage(BaseModel):
    sender_id: str
    message_id: str
    type: MessageType
    text: str | None = None
    object: MessageObject | None = None


class BotMessage(BaseModel):
    type: MessageType = MessageType.TEXT
    text: str | None = None
    object: MessageObject | None = None


class ProcessResult(BaseModel):
    sender_id: str
    message_id: str
    messages: list[BotMessage] = Field(default_factory=list)
    trace: list[dict] | None = None
