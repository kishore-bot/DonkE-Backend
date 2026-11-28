from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChapterView(BaseModel):
    chapter_id: str
    act: int
    title: str
    rival: str
    opens_at: datetime
    requires: str | None
    coins: int
    points: int
    status: Literal["ready", "cleared", "scheduled", "sign_in", "prerequisite"]
