from secrets import token_urlsafe
from typing import Literal
from uuid import UUID, uuid4

from donke_engine import PracticeGame

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.game.commands import hint_game, play_game, validate_retry
from app.modules.game.repositories.practice import (
    PracticeRepository,
    RecordedPlay,
)
from app.modules.game.schemas import (
    GameUpdate,
    PracticeCreated,
    PracticeHint,
    PracticePlayRequest,
)
from app.modules.game.seeded import SeededDuel, build_duel
from app.modules.game.story_state import StoryPin


class PracticeService:
    def __init__(self, repository: PracticeRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def create(
        self,
        seats: int,
        level: Literal["easy", "medium", "hard"] = "medium",
        client: str = "unknown",
        *,
        story: StoryPin | None = None,
        seed: int = 0,
    ) -> PracticeCreated:
        self.repository.reserve(client, self.settings)
        try:
            # Bots may play before the human's first turn: outside the table lock.
            game = (
                build_duel(seed, story)
                if story
                else PracticeGame(seats, level, iterations=200)
            )
            update = GameUpdate.model_validate_json(game.snapshot())
            game_id, token = uuid4(), token_urlsafe(32)
            response = PracticeCreated(
                game_id=game_id,
                access_token=token,
                **update.model_dump(),
            )
            self.repository.save(
                game_id,
                client,
                token,
                game,
                story,
                self.settings.practice_session_ttl_seconds,
            )
        except BaseException:
            self.repository.release(client)
            raise
        return response

    def story_decision(self, game_id: UUID, token: str) -> tuple[StoryPin, SeededDuel]:
        session = self.repository.get(game_id, token)
        with session.lock:
            if session.story is None or not isinstance(session.game, SeededDuel):
                raise AppError(404, "story_not_found", "Story attempt not found")
            if not session.finished:
                raise AppError(409, "story_in_progress", "Finish the story duel first")
            return session.story, session.game

    def hint(self, game_id: UUID, token: str) -> PracticeHint:
        # Play publishes a new game instance. Readers can use the captured version.
        # Repeated requests for one position wait for and reuse a single search.
        session = self.repository.get(game_id, token)
        with session.hint_lock:
            game = session.game
            if session.hint is None or session.hint[0] is not game:
                session.hint = (
                    game,
                    hint_game(game, self.settings.practice_hint_iterations),
                )
            return session.hint[1]

    def snapshot(self, game_id: UUID, token: str) -> GameUpdate:
        game = self.repository.get(game_id, token).game
        return GameUpdate.model_validate_json(game.snapshot())

    def play(
        self, game_id: UUID, token: str, command: PracticePlayRequest
    ) -> GameUpdate:
        session = self.repository.get(game_id, token)
        with session.lock:
            previous = session.plays.get(command.request_id)
            if previous is not None:
                validate_retry(previous.command, command)
                return previous.outcome
            next_game, update = play_game(session.game, command)
            session.plays[command.request_id] = RecordedPlay(command, update)
            session.game = next_game
            session.finished = update.view.outcome is not None
            return update
