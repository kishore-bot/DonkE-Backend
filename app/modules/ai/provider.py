from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


class Choice(BaseModel):
    key: str = Field(max_length=40)


@dataclass(frozen=True, slots=True)
class Selected:
    key: str
    tokens: int = 0


@dataclass(frozen=True, slots=True)
class Written:
    text: str
    tokens: int = 0


@dataclass(frozen=True, slots=True)
class Models:
    """Model ids a provider uses. They key caches and stored embeddings, so a
    switch of provider or model never reuses another model's output."""

    text: str
    voice: str
    embedding: str


class AIProvider(Protocol):
    """What DonkE needs from an AI backend. Implementations live in
    app/modules/ai/providers.py and are chosen by DONKE_AI_PROVIDER."""

    models: Models

    async def select(self, task: str, prompt: str) -> Selected: ...
    async def write(self, task: str, prompt: str) -> Written: ...
    async def render(self, text: str, voice: str) -> bytes: ...
    async def embed(self, texts: list[str], *, query: bool) -> list[list[float]]: ...
    async def close(self) -> None: ...
