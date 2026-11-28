import json
from dataclasses import asdict

from donke_engine import OnlineGame

from app.modules.game.dto.decisions import RivalDecision, StrikeDecision
from app.modules.game.dto.story_pin import RivalIntent, StoryPin
from app.modules.game.helpers.story_rules import objective, public_event
from app.modules.game.schemas.cards import Suit
from app.modules.game.schemas.story import StoryEvent, StoryRoute


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
        strike_decision: StrikeDecision | None = None,
        route: StoryRoute | None = None,
        journal: tuple[StoryEvent, ...] = (),
        rival_budget: int | None = None,
        rival_avoid_suit: Suit | None = None,
        rival_expert: bool = False,
    ):
        self.game = game
        self.seed = seed
        # None is unused, zero is resolved, one or two are open trick slots.
        self.remaining = remaining
        self.intent: RivalIntent = intent
        self.decision = decision
        self.strike_decision = strike_decision
        self.route: StoryRoute | None = route
        self.journal = journal
        self.rival_budget = rival_budget
        self.rival_avoid_suit: Suit | None = rival_avoid_suit
        self.rival_expert = rival_expert
        self.events: list[dict] = []
        self.advance_rival()

    def advance_rival(self) -> None:
        while self.game.turn == 1:
            card = self.rival_card()
            assert card is not None
            if (
                self.decision is None
                and len(json.loads(self.game.view(1))["legal_moves"]) > 1
            ):
                self.decision = RivalDecision(self.game.snapshot(), card)
            self.events.extend(json.loads(self.game.play(1, card)))

    def rival_card(self) -> str | None:
        budget = self.rival_budget
        if self.rival_expert:
            avoid = self.rival_avoid_suit if self.intent == "pressure" else None
            if searched := self.game.story_move(1, avoid):
                return searched
        level = "hard" if self.intent == "pressure" or budget else "medium"
        if budget and self.intent == "pressure" and self.rival_avoid_suit:
            scores = json.loads(self.game.evaluate(1, budget, self.seed))
            best = scores[0]
            pivot = next(
                (
                    move
                    for move in scores
                    if move["card"]["suit"] != self.rival_avoid_suit
                    and move["visits"] >= max(3, best["visits"] // 3)
                    and move["safe_rate"] >= best["safe_rate"] - 0.02
                ),
                best,
            )
            return json.dumps(pivot["card"])
        return self.game.bot_move(
            1,
            level,
            iterations=120 if budget is None else budget,
            seed=self.seed,
        )

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
                "objective": self.objective().model_dump() if self.route else None,
            }
        )

    def available(self, view: dict) -> bool:
        return (
            self.route not in {"reef", "storm"}
            and self.remaining is None
            and view["turn"] == 0
            and view["version"] > 0
            and not view["table"]
        )

    def hint(self, iterations: int) -> str:
        return self.game.evaluate(0, iterations, self.seed)

    def objective(self):
        assert self.route is not None
        return objective(self.route, self.journal)

    def play(self, card: str, call_strike: bool) -> tuple[SeededDuel, str]:
        if call_strike and not self.available(self.player_view()):
            raise ValueError("strike_call_unavailable")
        opening = self.game.snapshot()
        game = OnlineGame.restore(opening)
        events = json.loads(game.play(0, card))
        duel = SeededDuel(
            game,
            self.seed,
            2 if call_strike else self.remaining,
            intent=self.intent,
            decision=self.decision,
            strike_decision=self.strike_decision,
            route=self.route,
            journal=self.journal,
            rival_budget=self.rival_budget,
            rival_avoid_suit=self.rival_avoid_suit,
            rival_expert=self.rival_expert,
        )
        rival_events = duel.events
        duel.events = [{"event": "strike_called", "target": 1}] if call_strike else []
        move = self.version
        recorded = (
            [
                StoryEvent(
                    sequence=len(self.journal) + 1,
                    move=move,
                    kind="strike_called",
                    seat=0,
                    recipient=1,
                )
            ]
            if call_strike
            else []
        )
        for event in events + rival_events:
            if event["event"] == "card_played":
                move += 1
            if visible := public_event(
                event, len(self.journal) + len(recorded) + 1, move
            ):
                recorded.append(visible)
            duel.events.append(event)
            if duel.remaining and (result := duel.resolve(event)) is not None:
                resolution = {"event": "strike_call_resolved", "success": result}
                duel.events.append(resolution)
                recorded.append(
                    StoryEvent(
                        sequence=len(self.journal) + len(recorded) + 1,
                        move=move,
                        kind="strike_resolved",
                        success=result,
                    )
                )
                if result:
                    view = self.player_view()
                    if len(view["legal_moves"]) > 1:
                        duel.strike_decision = StrikeDecision(
                            view["version"] + 1, opening, card
                        )
        duel.journal = (*self.journal, *recorded)
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

    def freeze(self) -> dict:
        return {
            "native": self.game.snapshot(),
            "seed": self.seed,
            "remaining": self.remaining,
            "intent": self.intent,
            "decision": asdict(self.decision) if self.decision is not None else None,
            "strike_decision": asdict(self.strike_decision)
            if self.strike_decision is not None
            else None,
            "events": self.events,
            "route": self.route,
            "journal": [event.model_dump(exclude_none=True) for event in self.journal],
            "rival_budget": self.rival_budget,
            "rival_avoid_suit": self.rival_avoid_suit,
            "rival_expert": self.rival_expert,
        }

    @classmethod
    def restore(cls, snapshot: dict) -> SeededDuel:
        game = OnlineGame.restore(snapshot["native"])
        assert game.turn != 1
        first = snapshot["decision"]
        strike = snapshot.get("strike_decision")
        duel = cls(
            game,
            snapshot["seed"],
            snapshot["remaining"],
            intent=snapshot["intent"],
            decision=RivalDecision(**first) if first else None,
            strike_decision=StrikeDecision(**strike) if strike else None,
            route=snapshot.get("route"),
            journal=tuple(
                StoryEvent.model_validate(event)
                for event in snapshot.get("journal", ())
            ),
            rival_budget=snapshot.get("rival_budget"),
            rival_avoid_suit=snapshot.get("rival_avoid_suit"),
            rival_expert=snapshot.get("rival_expert", False),
        )
        duel.events = snapshot["events"]
        return duel


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
