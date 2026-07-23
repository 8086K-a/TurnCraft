from pydantic import BaseModel, Field, model_validator


class ChatObject(BaseModel):
    type: str
    id: str
    title: str | None = None
    attributes: dict = Field(default_factory=dict)


class ChatRequest(BaseModel):
    sender_id: str
    message_id: str | None = None
    text: str | None = None
    object: ChatObject | None = None

    @model_validator(mode="after")
    def validate_message_content(self):
        if (self.text is None) == (self.object is None):
            raise ValueError("exactly one of text or object must be provided")
        if self.text is not None and not self.text.strip():
            raise ValueError("text must not be blank")
        return self


class ChatBotMessage(BaseModel):
    text: str | None = None
    object: ChatObject | None = None


class ChatResponse(BaseModel):
    sender_id: str
    message_id: str
    messages: list[ChatBotMessage]
    trace: list[dict] | None = None


class HistoryMessage(BaseModel):
    role: str # user or bot
    text: str | None = None
    object: ChatObject | None = None


class HistoryResponse(BaseModel):
    sender_id: str
    messages: list[HistoryMessage]
