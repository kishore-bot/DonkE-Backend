from typing import Literal

from pydantic import BaseModel


class OnlineHealth(BaseModel):
    status: Literal["ok"] = "ok"
    heartbeat_age_ms: int
    oldest_due_turn_lag_ms: int
