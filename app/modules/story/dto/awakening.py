from dataclasses import dataclass

from app.modules.story.schemas.awakening import StepId


@dataclass(frozen=True, slots=True)
class Step:
    text: str
    source: str
    requires: tuple[StepId, ...] = ()
