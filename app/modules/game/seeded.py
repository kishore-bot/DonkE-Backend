import json
from dataclasses import dataclass
from typing import Literal

from donke_engine import OnlineGame

type RivalIntent = Literal["steady", "pressure"]


@dataclass(frozen=True, slots=True)
class RivalDecision:
    snapshot: str
    card: str


class SeededDuel:
    """Expose one human seat through the existing practice move protocol."""

    def __init__(
        self,
        game: OnlineGame,
        seed: int,
        remaining: int | None = None,
        *,
        intent: RivalIntent = "steady",
        decision: RivalDecision | None = None,
    ):
        self.game = game
        self.seed = seed
        # None is unused, zero is resolved, one or two are open trick slots.
        self.remaining = remaining
        self.intent: RivalIntent = intent
        self.decision = decision
        self.events: list[dict] = []
        self.advance_rival()

    def advance_rival(self) -> None:
        while self.game.turn == 1:
            level = "hard" if self.intent == "pressure" else "medium"
            card = self.game.bot_move(1, level, iterations=120, seed=self.seed)
            assert card is not None
            if (
                self.decision is None
                and len(json.loads(self.game.view(1))["legal_moves"]) > 1
            ):
                self.decision = RivalDecision(self.game.snapshot(), card)
            self.events.extend(json.loads(self.game.play(1, card)))

    @property
    def version(self) -> int:
        return self.player_view()["version"]

    def player_view(self) -> dict:
        return json.loads(self.game.view(0))

    def snapshot(self) -> str:
        view = self.player_view()
        return json.dumps(
            {
                "view": view,
                "events": self.events,
                "can_call_strike": self.available(view),
            }
        )

    def available(self, view: dict) -> bool:
        return (
            self.remaining is None
            and view["turn"] == 0
            and view["version"] > 0
            and not view["table"]
        )

    def hint(self, iterations: int) -> str:
        return self.game.evaluate(0, iterations, self.seed)

    def play(self, card: str, call_strike: bool) -> tuple[SeededDuel, str]:
        if call_strike and not self.available(self.player_view()):
            raise ValueError("strike_call_unavailable")
        game = OnlineGame.restore(self.game.snapshot())
        events = json.loads(game.play(0, card))
        duel = SeededDuel(
            game,
            self.seed,
            2 if call_strike else self.remaining,
            intent=self.intent,
            decision=self.decision,
        )
        rival_events = duel.events
        duel.events = [{"event": "strike_called", "target": 1}] if call_strike else []
        for event in events + rival_events:
            duel.events.append(event)
            if duel.remaining and (result := duel.resolve(event)) is not None:
                duel.events.append({"event": "strike_call_resolved", "success": result})
        return duel, duel.snapshot()

    def resolve(self, event: dict) -> bool | None:
        kind = event["event"]
        if kind == "vettu" and event["cutter"] == 0:
            self.remaining = 0
            return event["receiver"] == 1
        if kind in {"trick_discarded", "vettu"} and self.remaining:
            self.remaining -= 1
            if self.remaining == 0:
                return False
        if kind == "game_finished" or (kind == "player_escaped" and event["seat"] == 0):
            self.remaining = 0
            return False
        return None
