"""PostgreSQL storage for signed-in story attempts."""

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hmac import compare_digest, digest
from uuid import UUID, uuid4

from donke_engine import OnlineGame
from pydantic import TypeAdapter
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.game.commands import hint_game, play_game, validate_retry
from app.modules.game.models import StoryDuel, StoryDuelCommand
from app.modules.game.repository import StoryPin
from app.modules.game.rival_memory import remember
from app.modules.game.schemas import (
    GameUpdate,
    PracticeCreated,
    PracticeHint,
    PracticePlayRequest,
    StoryEvent,
)
from app.modules.game.seeded import SeededDuel
from app.modules.game.story_rules import public_event
from app.modules.identity.models import Player
from app.modules.progression.service import lock_season_schedule

PIN = TypeAdapter(StoryPin)
FINISHED_RETENTION = timedelta(days=1)


def unavailable() -> AppError:
    return AppError(404, "practice_not_found", "Practice match not found")


class StoryStore:
    def __init__(self, platform: Platform):
        self.platform = platform

    def token(self, game_id: UUID) -> str:
        secret = self.platform.settings.auth_secret
        assert secret is not None
        mac = digest(
            secret.get_secret_value().encode(),
            b"donke-story-attempt-v1:" + game_id.bytes,
            "sha256",
        )
        return urlsafe_b64encode(mac).decode().rstrip("=")

    def accepts(self, game_id: UUID, token: str) -> bool:
        return compare_digest(self.token(game_id).encode(), token.encode())

    def response(self, record: StoryDuel, game: SeededDuel) -> PracticeCreated:
        return PracticeCreated(
            **GameUpdate.model_validate_json(game.snapshot()).model_dump(),
            game_id=record.id,
            access_token=self.token(record.id),
        )

    async def create(self, pin: StoryPin, seed: int) -> PracticeCreated:
        player = pin.player_id
        assert player is not None
        config = self.platform.settings
        async with self.platform.sessions.begin() as db:
            await lock_season_schedule(db, read=True)
            locked = await db.scalar(
                select(Player.id).where(Player.id == player).with_for_update()
            )
            if locked is None:
                raise unavailable()
            now = datetime.now(UTC)
            active = await db.scalar(
                select(func.count(StoryDuel.id)).where(
                    StoryDuel.player_id == player,
                    StoryDuel.expires_at > now,
                    StoryDuel.finished.is_(False),
                )
            )
            if (active or 0) >= config.practice_sessions_per_client:
                raise AppError(
                    429, "practice_limit", "Resume one of your story duels first"
                )
            game = await run_in_threadpool(build_duel, seed, pin)
            row = StoryDuel(
                id=uuid4(),
                season_id=pin.season_id,
                player_id=player,
                created_at=now,
                expires_at=now + timedelta(seconds=config.practice_session_ttl_seconds),
                pin=PIN.dump_python(pin, mode="json"),
                duel=game.freeze(),
                finished=False,
            )
            db.add(row)
            return self.response(row, game)

    async def load(
        self,
        db: AsyncSession,
        game_id: UUID,
        token: str,
        *,
        lock: bool = False,
        player: UUID | None = None,
    ) -> StoryDuel:
        if not self.accepts(game_id, token):
            raise unavailable()
        row = await db.get(StoryDuel, game_id, with_for_update=lock)
        if (
            row is None
            or row.expires_at <= datetime.now(UTC)
            or (player is not None and row.player_id != player)
        ):
            raise unavailable()
        return row

    async def resume(self, player: UUID) -> tuple[StoryPin, PracticeCreated] | None:
        async with self.platform.sessions() as db:
            row = await db.scalar(
                select(StoryDuel)
                .where(
                    StoryDuel.player_id == player,
                    StoryDuel.expires_at > datetime.now(UTC),
                    StoryDuel.receipt.is_(None),
                )
                .order_by(StoryDuel.created_at.desc(), StoryDuel.id)
                .limit(1)
            )
        if row is None:
            return None
        return PIN.validate_python(row.pin), self.response(
            row, SeededDuel.restore(row.duel)
        )

    async def snapshot(self, game_id: UUID, token: str) -> GameUpdate:
        async with self.platform.sessions() as db:
            row = await self.load(db, game_id, token)
        return GameUpdate.model_validate_json(SeededDuel.restore(row.duel).snapshot())

    async def hint(self, game_id: UUID, token: str) -> PracticeHint:
        async with self.platform.sessions() as db:
            row = await self.load(db, game_id, token)
        return await run_in_threadpool(
            hint_game,
            SeededDuel.restore(row.duel),
            self.platform.settings.practice_hint_iterations,
        )

    async def play(
        self, game_id: UUID, token: str, command: PracticePlayRequest
    ) -> GameUpdate:
        async with self.platform.sessions.begin() as db:
            row = await self.load(db, game_id, token, lock=True)
            prior = await db.get(StoryDuelCommand, (game_id, command.request_id))
            if prior is not None:
                validate_retry(
                    PracticePlayRequest.model_validate(prior.command), command
                )
                return GameUpdate.model_validate(prior.update)
            game = await self.replay_game(db, row)
            next_game, update = await run_in_threadpool(play_game, game, command)
            assert isinstance(next_game, SeededDuel)
            row.duel = next_game.freeze()
            row.finished = update.view.outcome is not None
            if row.finished:
                finished_at = datetime.now(UTC)
                row.expires_at = finished_at + FINISHED_RETENTION
                await remember(
                    db, PIN.validate_python(row.pin), finished_at, next_game.journal
                )
            db.add(
                StoryDuelCommand(
                    duel_id=game_id,
                    request_id=command.request_id,
                    command=command.model_dump(mode="json"),
                    update=update.model_dump(mode="json"),
                )
            )
            return update

    async def finished(
        self, game_id: UUID, token: str, *, player: UUID | None = None
    ) -> tuple[StoryPin, SeededDuel]:
        async with self.platform.sessions() as db:
            row = await self.load(db, game_id, token, player=player)
            if not row.finished:
                raise AppError(409, "story_in_progress", "Finish the story duel first")
            return PIN.validate_python(row.pin), await self.replay_game(db, row)

    @staticmethod
    async def replay_game(db: AsyncSession, row: StoryDuel) -> SeededDuel:
        game = SeededDuel.restore(row.duel)
        if "journal" in row.duel:
            return game
        history = await db.scalars(
            select(StoryDuelCommand.update)
            .where(StoryDuelCommand.duel_id == row.id)
            .order_by(StoryDuelCommand.command["expected_version"].astext.cast(Integer))
        )
        journal: list[StoryEvent] = []
        for update in history:
            events = update["events"]
            move = update["view"]["version"] - sum(
                event["event"] == "card_played" for event in events
            )
            for event in events:
                move += event["event"] == "card_played"
                if visible := public_event(event, len(journal) + 1, move):
                    journal.append(visible)
        game.journal = tuple(journal)
        return game


def build_duel(seed: int, pin: StoryPin) -> SeededDuel:
    return SeededDuel(
        OnlineGame.seeded(2, seed),
        seed,
        intent=pin.intent,
        route=pin.route,
        rival_budget=pin.rival_budget,
        rival_avoid_suit=pin.rival_avoid_suit,
        rival_expert=pin.rival_expert,
    )


def for_attempt(
    platform: Platform | None, game_id: UUID, token: str
) -> StoryStore | None:
    if platform is None or platform.settings.auth_secret is None:
        return None
    store = StoryStore(platform)
    return store if store.accepts(game_id, token) else None


async def prune_expired(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(StoryDuel).where(StoryDuel.expires_at <= now))
