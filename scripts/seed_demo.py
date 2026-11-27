"""Seed stable fixtures in an explicitly enabled demo database."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from donke_engine import OnlineGame
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import Platform, open_platform
from app.core.schema import check_storage_ready
from app.modules.identity.repository import find_or_create_player
from app.modules.identity.schemas import Language, Profile
from app.modules.identity.service import IdentityService
from app.modules.lobby.repository import LobbyRepository
from app.modules.lobby.service import LobbyService
from app.modules.matches.schemas import EventBatch, GameSeat, MatchReplay
from app.modules.matches.settlement import persist
from app.modules.progression.models import Season
from app.modules.social.services.friends import FriendsService

DEMO_SUBJECTS: tuple[tuple[str, str, Language], ...] = (
    ("donke-demo:v1:anila", "Demo Anila", "ml"),
    ("donke-demo:v1:arun", "Demo Arun", "en"),
)
DEMO_SEASON = uuid5(NAMESPACE_URL, "urn:donke:demo:v1:season")
SEEDS = (301, 302, 303, 304, 305, 306)


class DemoSession(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    player_id: UUID
    access_token: str = Field(repr=False)


class DemoSessions(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    players: tuple[DemoSession, DemoSession]
    replay_id: UUID


def replay_id(seed: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"urn:donke:demo:v1:replay:{seed}")


def make_replay(players: list[Profile], seed: int) -> MatchReplay:
    game = OnlineGame.seeded(len(players), seed)
    events = [
        EventBatch(sequence=1, events=[{"event": "game_started", "turn": game.turn}])
    ]
    while (seat := game.turn) is not None:
        played = json.loads(game.play(seat))
        events.append(EventBatch(sequence=len(events) + 1, events=played))
    outcome = events[-1].events[-1]["outcome"]
    return MatchReplay(
        id=replay_id(seed),
        room_id=uuid5(NAMESPACE_URL, f"urn:donke:demo:v1:room:{seed}"),
        mode="classic",
        seats=[
            GameSeat(
                player_id=player.id,
                display_name=player.display_name,
                bot=False,
                ready=True,
            )
            for player in players
        ],
        outcome=outcome,
        events=events,
    )


async def seed(platform: Platform) -> list[Profile]:
    if not platform.settings.demo_mode:
        raise AppError(
            403,
            "demo_disabled",
            "Enable DONKE_DEMO_MODE on a dedicated demo database first",
        )
    await check_storage_ready(platform)
    async with platform.sessions.begin() as db:
        # Use the season scheduling lock so seeding cannot race with admin scheduling.
        await db.execute(text("SELECT pg_advisory_xact_lock(470052)"))
        players: list[Profile] = []
        for subject, name, language in DEMO_SUBJECTS:
            player = await find_or_create_player(db, subject)
            player.display_name = name
            player.language = language
            players.append(Profile.model_validate(player))
        now = datetime.now(UTC)
        active = await db.scalar(
            select(Season.id)
            .where(Season.starts_at <= now, Season.ends_at > now)
            .limit(1)
        )
        if active is None:
            upcoming = await db.scalar(
                select(Season.starts_at)
                .where(Season.starts_at > now)
                .order_by(Season.starts_at)
                .limit(1)
            )
            ends = now + timedelta(days=28)
            db.add(
                Season(
                    id=DEMO_SEASON
                    if await db.get(Season, DEMO_SEASON) is None
                    else None,
                    theme="Monsoon Demo",
                    starts_at=now,
                    ends_at=min(upcoming, ends) if upcoming is not None else ends,
                )
            )

    lobby = LobbyService(LobbyRepository(platform.redis, platform.settings))
    social = FriendsService(platform, lobby)
    await social.request(players[0].id, players[1].id)
    # If a demo player started the request in the reverse direction, accept as its recipient.
    edge = next(
        item
        for item in await social.friends(players[0].id)
        if item.player.id == players[1].id
    )
    if edge.status == "incoming":
        await social.update_friend(players[0].id, players[1].id, accept=True)
    elif edge.status == "outgoing":
        await social.update_friend(players[1].id, players[0].id, accept=True)
    for seed_value in SEEDS:
        await persist(platform, make_replay(players, seed_value))
    return players


async def sessions(platform: Platform, players: list[Profile]) -> DemoSessions:
    identity = IdentityService(platform)
    result = []
    for (subject, _, _), player in zip(DEMO_SUBJECTS, players, strict=True):
        tokens = await identity.sign_in(subject)
        result.append(
            DemoSession(player_id=player.id, access_token=tokens.access_token)
        )
    return DemoSessions(players=(result[0], result[1]), replay_id=replay_id(SEEDS[0]))


def write_sessions(path: Path, data: DemoSessions) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(data.model_dump_json(indent=2) + "\n")


async def run(path: Path | None) -> None:
    settings = Settings()
    if not settings.demo_mode:
        raise AppError(
            403,
            "demo_disabled",
            "Enable DONKE_DEMO_MODE on a dedicated demo database first",
        )
    async with open_platform(settings) as platform:
        players = await seed(platform)
        if path is not None:
            write_sessions(path, await sessions(platform, players))
    print(f"Seeded {len(players)} demo profiles and {len(SEEDS)} archived matches.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sessions", type=Path, help="Write fresh access tokens to a new private file"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.sessions))
    except (AppError, FileExistsError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
