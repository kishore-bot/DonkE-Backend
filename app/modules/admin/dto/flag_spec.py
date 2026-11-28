from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FlagSpec:
    kind: type
    description: str
    minimum: int = 0
    maximum: int = 0
