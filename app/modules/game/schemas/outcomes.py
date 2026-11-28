from typing import Annotated, Literal

from pydantic import BaseModel, Field


class DonkeyOutcome(BaseModel):
    reason: Literal["donkey"]
    seat: int


class AllSafeOutcome(BaseModel):
    reason: Literal["all_safe"]


class PlayLimitOutcome(BaseModel):
    reason: Literal["play_limit"]


Outcome = Annotated[
    DonkeyOutcome | AllSafeOutcome | PlayLimitOutcome,
    Field(discriminator="reason"),
]
