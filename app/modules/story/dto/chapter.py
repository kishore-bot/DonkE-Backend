from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Chapter:
    id: str
    act: int
    title: str
    rival: str
    seed: int
    coins: int
    points: int
    requires: str | None = None
