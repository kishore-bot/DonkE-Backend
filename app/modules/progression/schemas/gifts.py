from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
