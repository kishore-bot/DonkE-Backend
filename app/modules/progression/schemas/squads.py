from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.progression.helpers.catalog import SQUAD_COSMETIC
from app.modules.progression.helpers.squads import GIFT_COINS


class SquadProgress(BaseModel):
    season_id: UUID
    title: str
    completed: int
    target: int
    contributed: bool
    claim_deadline: datetime
    can_claim: bool
    claimed: bool
    coins: int = GIFT_COINS
    cosmetic: str = SQUAD_COSMETIC


class SquadOverview(BaseModel):
    active_season_id: UUID | None
    squads: list[SquadProgress]
