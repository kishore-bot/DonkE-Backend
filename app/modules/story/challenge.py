from datetime import UTC, datetime, timedelta
from hmac import digest
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.game.schemas import StoryRoute, Suit
from app.modules.game.seeded import RivalIntent, SeededDuel
from app.modules.game.story_state import StoryPin
from app.modules.progression.season_content import PACKS, CharacterPreview
from app.modules.story.chapters import OPENING_CHAPTER

AUDIENCE = "donke-story-challenge-v1"


class SharedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escaped: bool
    plays: int = Field(ge=0, le=1000)


class ChallengeView(BaseModel):
    pack_title: str
    rival: str
    character: CharacterPreview
    result: SharedResult
    expires_at: datetime


class ChallengeLink(BaseModel):
    code: str


class ChallengePin(BaseModel):
    season_id: UUID
    pack_key: str
    character_id: str
    intent: RivalIntent
    chapter_id: str = OPENING_CHAPTER
    result: SharedResult
    exp: datetime
    route: StoryRoute | None = None
    rival_budget: int | None = Field(default=None, ge=0, le=256)
    rival_avoid_suit: Suit | None = None
    rival_expert: bool = False

    def story(self) -> StoryPin:
        return StoryPin(
            self.season_id,
            self.pack_key,
            self.character_id,
            None,
            intent=self.intent,
            chapter_id=self.chapter_id,
            route=self.route,
            rival_budget=self.rival_budget,
            rival_avoid_suit=self.rival_avoid_suit,
            rival_expert=self.rival_expert,
        )


def signing_key(platform: Platform) -> bytes:
    secret = platform.settings.auth_secret
    assert secret is not None
    return digest(secret.get_secret_value().encode(), AUDIENCE.encode(), "sha256")


def challenge_link(
    platform: Platform, pin: StoryPin, duel: SeededDuel
) -> ChallengeLink:
    view = duel.player_view()
    payload = ChallengePin(
        season_id=pin.season_id,
        pack_key=pin.pack_key,
        character_id=pin.character_id,
        intent=pin.intent,
        chapter_id=pin.chapter_id,
        route=pin.route,
        rival_budget=pin.rival_budget,
        rival_avoid_suit=pin.rival_avoid_suit,
        rival_expert=pin.rival_expert,
        result=SharedResult(escaped=0 in view["escape_order"], plays=view["version"]),
        exp=datetime.now(UTC) + timedelta(days=30),
    )
    return ChallengeLink(
        code=jwt.encode(
            payload.model_dump(mode="json", exclude={"exp"}, exclude_none=True)
            | {"aud": AUDIENCE, "exp": int(payload.exp.timestamp())},
            signing_key(platform),
            algorithm="HS256",
        )
    )


def read_challenge(platform: Platform, code: str) -> ChallengePin:
    try:
        payload = jwt.decode(
            code,
            signing_key(platform),
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["aud", "exp"]},
        )
        return ChallengePin.model_validate(payload)
    except (jwt.InvalidTokenError, ValidationError) as error:
        raise AppError(
            404, "challenge_not_found", "This story challenge has expired or is invalid"
        ) from error


def challenge_character(pin: ChallengePin) -> tuple[str, CharacterPreview]:
    pack = PACKS.get(pin.pack_key)
    if pack is not None:
        for character in pack.cast:
            if character.id == pin.character_id:
                return pack.title, character
    raise AppError(404, "challenge_not_found", "The story pack is unavailable")
