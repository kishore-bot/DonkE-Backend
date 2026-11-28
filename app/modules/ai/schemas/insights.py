from pydantic import BaseModel

from app.modules.ai.schemas.coaching import Situation
from app.modules.ai.schemas.source import Source


class Insights(BaseModel):
    matches: int
    decisions: int
    accuracy: float | None
    strongest: Situation | None
    focus: Situation | None
    mistake_rates: dict[Situation, float]
    summary: str
    source: Source


class Roast(BaseModel):
    donkey: str
    text: str
    source: Source
    svg: str
