from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.modules.game.schemas import PlayRequest


class SocketPlay(PlayRequest):
    action: Literal["play_card"]


class SocketLeave(BaseModel):
    action: Literal["leave"]


class SocketPing(BaseModel):
    action: Literal["ping"]


class SocketEmote(BaseModel):
    action: Literal["emote"]
    emote: str = Field(min_length=1, max_length=80)


class SocketChat(BaseModel):
    action: Literal["chat"]
    text: str = Field(min_length=1, max_length=400)


Command = Annotated[
    SocketPlay | SocketLeave | SocketPing | SocketEmote | SocketChat,
    Field(discriminator="action"),
]


COMMAND = TypeAdapter(Command)


class SocketTicket(BaseModel):
    ticket: str
