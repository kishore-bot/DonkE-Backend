from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def window(self) -> SeasonCreate:
        if self.starts_at >= self.ends_at:
            raise ValueError("The season must end after it starts")
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
