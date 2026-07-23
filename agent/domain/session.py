from pydantic import BaseModel, Field

from .turn import Turn


class Session(BaseModel):
    session_id: str
    started_at: float
    last_activity_at: float
    closed_at: float | None = None
    turns: list[Turn] = Field(default_factory=list)
