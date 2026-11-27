"""Coin store catalog, festival rotation, achievements, season perks and the
streak bonus track. Pure data and rules; the service applies them."""

from dataclasses import dataclass
from datetime import date

# (month, day) inclusive. A window may wrap the new year.
type Window = tuple[tuple[int, int], tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    label: str
    slot: str
    price: int
    festival: str | None = None
    window: Window | None = None


CATALOG = {
    "monsoon_back": CatalogProduct("Monsoon card back", "card_back", 60),
    "poorayil_frame": CatalogProduct("Poorayil festival frame", "frame", 90),
    "kettuvallam_title": CatalogProduct("Kettuvallam Captain", "title", 75),
    "vishu_kani_frame": CatalogProduct(
        "Vishu Kani frame", "frame", 110, "Vishu", ((4, 1), (4, 20))
    ),
    "pooram_elephant_title": CatalogProduct(
        "Pooram Elephant", "title", 100, "Thrissur Pooram", ((4, 20), (5, 15))
    ),
    "onam_pookalam_back": CatalogProduct(
        "Onam Pookalam card back", "card_back", 120, "Onam", ((8, 15), (9, 15))
    ),
    "christmas_star_back": CatalogProduct(
        "Christmas Star card back", "card_back", 100, "Christmas", ((12, 10), (1, 5))
    ),
}


def _key(day: date) -> tuple[int, int]:
    return (day.month, day.day)


def in_window(window: Window | None, today: date) -> bool:
    if window is None:
        return True
    start, end = window
    if start <= end:
        return start <= _key(today) <= end
    return _key(today) >= start or _key(today) <= end


def window_end(window: Window | None, today: date) -> date | None:
    """Last day the item can be bought, if it is on sale today."""
    if window is None or not in_window(window, today):
        return None
    (start_month, _), (month, day) = window
    year = today.year + (1 if month < start_month and today.month >= start_month else 0)
    return date(year, month, day)


@dataclass(frozen=True, slots=True)
class AchievementSpec:
    title: str
    description: str
    stat: str
    target: int
    coins: int


ACHIEVEMENTS = {
    "first_escape": AchievementSpec("First Escape", "Escape a match", "escapes", 1, 20),
    "escape_artist": AchievementSpec(
        "Escape Artist", "Escape 25 matches", "escapes", 25, 100
    ),
    "first_crown": AchievementSpec(
        "First Crown", "Finish first in a match", "firsts", 1, 25
    ),
    "crown_collector": AchievementSpec(
        "Crown Collector", "Finish first 20 times", "firsts", 20, 150
    ),
    "regular": AchievementSpec("Regular", "Play 10 matches", "games", 10, 30),
    "veteran": AchievementSpec("Veteran", "Play 100 matches", "games", 100, 200),
    "vettu_master": AchievementSpec(
        "Vettu Master", "Give 50 Vettus", "cuts_given", 50, 120
    ),
    "thick_skin": AchievementSpec(
        "Thick Skin", "Pick up 100 cards from Vettus", "cards_picked", 100, 60
    ),
    "untouchable": AchievementSpec(
        "Untouchable",
        "Avoid being the Donkey 10 matches in a row",
        "best_safe_streak",
        10,
        150,
    ),
    "proud_donkey": AchievementSpec(
        "Proud Donkey", "Be the Donkey 25 times and keep playing", "donkeys", 25, 50
    ),
}


@dataclass(frozen=True, slots=True)
class Perk:
    key: str
    title: str
    tier: int


PERKS = [
    Perk("coin_boost", "+10% match coins", 5),
    Perk("bank_boost", "Season Bank keeps a quarter of match coins", 15),
    Perk("season_emote", "Exclusive season emote at tier 25", 25),
]
TIER_POINTS = 10
TIERS = 30
STREAK_DAYS = 5
SQUAD_COSMETIC = "Squad Finale frame"
# Bonus tier -> (streak stars needed, cosmetic slot granted).
BONUS_TRACK = {1: (1, "emote"), 2: (2, "card_back"), 3: (3, "title"), 4: (4, "frame")}


def tier_reached(points: int) -> int:
    return min(TIERS, points // TIER_POINTS)


def active_perks(points: int) -> set[str]:
    reached = tier_reached(points)
    return {perk.key for perk in PERKS if reached >= perk.tier}


def boosted_coins(base: int, perks: set[str]) -> int:
    return base + base // 10 if "coin_boost" in perks else base


def bank_share(coins: int, perks: set[str]) -> int:
    return coins // 4 if "bank_boost" in perks else coins // 5
