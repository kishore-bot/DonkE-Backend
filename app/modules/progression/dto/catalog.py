from dataclasses import dataclass

# (month, day) inclusive. A window may wrap the new year.
type Window = tuple[tuple[int, int], tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    label: str
    slot: str
    price: int
    festival: str | None = None
    window: Window | None = None


@dataclass(frozen=True, slots=True)
class AchievementSpec:
    title: str
    description: str
    stat: str
    target: int
    coins: int


@dataclass(frozen=True, slots=True)
class Perk:
    key: str
    title: str
    tier: int
