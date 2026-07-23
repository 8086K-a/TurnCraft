from pydantic import BaseModel, Field

from .message import UserMessage, BotMessage


class Turn(BaseModel):
    turn_id: str
    input_message: UserMessage
    assistant_messages: list[BotMessage] = Field(default_factory=list)
