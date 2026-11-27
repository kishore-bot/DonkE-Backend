from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.progression.season_content import PACKS


class WalletView(BaseModel):
    coins: int


class CatalogItem(BaseModel):
    sku: str
    label: str
    slot: str
    price: int
    owned: bool
    equipped: bool
    festival: str | None = None
    available: bool = True
    available_until: date | None = None


class SeasonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    theme: str = Field(min_length=3, max_length=60)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str = Field(min_length=3, max_length=120)
    pack_key: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def window(self) -> SeasonCreate:
        if self.starts_at >= self.ends_at:
            raise ValueError("The season must end after it starts")
        if self.pack_key is not None:
            if self.pack_key not in PACKS:
                raise ValueError("Unknown season pack")
            start, end = (
                value.astimezone(UTC) for value in (self.starts_at, self.ends_at)
            )
            if start.time() != time.min or end - start != timedelta(days=21):
                raise ValueError("Packed seasons need 21 days starting at UTC midnight")
        return self


class CloseSeason(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=3, max_length=120)


class SeasonInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    theme: str
    starts_at: datetime
    ends_at: datetime
    closed_at: datetime | None
    pack_key: str | None = None
    # False when a later season had already started at close, so ratings
    # were left alone. None until the season is closed.
    ratings_reset: bool | None = None


class TierView(BaseModel):
    tier: int
    points: int
    coins: int
    reward: str | None = None
    claimed: bool


class PerkView(BaseModel):
    key: str
    title: str
    tier: int
    active: bool


class BonusView(BaseModel):
    tier: int
    stars: int
    reward: str
    claimed: bool


class ChallengeView(BaseModel):
    key: str
    title: str
    progress: int
    target: int
    points: int
    claimed: bool


class MySeason(BaseModel):
    season: SeasonInfo
    points: int
    bank: int
    peak_mmr: int
    tiers: list[TierView]
    weekly: list[ChallengeView]
    perks: list[PerkView]
    streak_days: int
    streak_target: int
    stars: int
    bonus: list[BonusView]


class EarnedGift(BaseModel):
    kind: Literal["tiers", "weekly", "bonus"]
    key: str
    title: str
    week: date | None = None
    act: int | None = None
    coins: int = 0
    points: int = 0
    cosmetic: str | None = None
    claimed: bool


class SeasonGifts(BaseModel):
    season_id: UUID
    title: str
    claim_deadline: datetime
    gifts: list[EarnedGift]


class Standing(BaseModel):
    player_id: UUID
    points: int
    peak_mmr: int


class AchievementView(BaseModel):
    key: str
    title: str
    description: str
    progress: int
    target: int
    coins: int
    unlocked_at: datetime | None


class AchievementsView(BaseModel):
    stats: dict[str, int]
    achievements: list[AchievementView]
