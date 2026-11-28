from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)


# Lobby chat --------------------------------------------------------------


class ChatMessage(BaseModel):
    id: str
    player_id: UUID
    name: str
    text: str
    at: datetime


class ChatPage(BaseModel):
    messages: list[ChatMessage]
    # Poll again with this. It moves past every message read, including ones
    # hidden by blocks, so a run of hidden messages can never stall polling.
    next_after: str | None
