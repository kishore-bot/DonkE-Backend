from datetime import datetime

from pydantic import BaseModel


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
