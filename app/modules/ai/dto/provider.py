from dataclasses import dataclass


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
