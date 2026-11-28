from typing import Literal

from pydantic import BaseModel

type Requirement = Literal["choose_character", "clear_duel", "earn_points"]


type StepId = Literal[
    "season_active",
    "choose_character",
    "clear_duel",
    "earn_points",
    "claim_window",
    "claim_form",
    "final_form",
]


type Status = Literal["complete", "ready", "blocked"]


class PathStep(BaseModel):
    id: StepId
    text: str
    source: str
    requires: tuple[StepId, ...]
    status: Status
