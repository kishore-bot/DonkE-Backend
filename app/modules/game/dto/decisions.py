from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RivalDecision:
    snapshot: str
    card: str


@dataclass(frozen=True, slots=True)
class StrikeDecision:
    move: int
    snapshot: str
    card: str
