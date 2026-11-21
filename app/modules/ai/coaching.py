"""Engine-grounded coaching: re-play a finished match from its opening deal,
score each of the player's real choices with the Rust engine, and turn the
biggest mistakes into tips. Gemini only rewords the tip sentences."""

import asyncio
import json
from typing import Any, Literal
from uuid import UUID

from donke_engine import OnlineGame
from pydantic import BaseModel
from sqlalchemy import DateTime, Double, ForeignKey, Index, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.core.errors import AppError
from app.core.platform import Base
from app.modules.ai.gateway import Gateway
from app.modules.ai.prompts import PROMPTS, Source, reword
from app.modules.identity.schemas import Language
from app.modules.matches.schemas import MatchReplay

ITERATIONS = 200
GOOD_GAP = 0.03
MISTAKE_GAP = 0.15
TOP_MISTAKES = 3
Situation = Literal["leading", "following", "cutting", "near_escape"]
SITUATIONS: tuple[Situation, ...] = ("leading", "following", "cutting", "near_escape")

RANKS = {
    "Two": "2",
    "Three": "3",
    "Four": "4",
    "Five": "5",
    "Six": "6",
    "Seven": "7",
    "Eight": "8",
    "Nine": "9",
    "Ten": "10",
    "Jack": "J",
    "Queen": "Q",
    "King": "K",
    "Ace": "A",
}
SUITS = {"Spades": "♠", "Hearts": "♥", "Diamonds": "♦", "Clubs": "♣"}


def label(card: dict[str, Any]) -> str:
    return RANKS[card["rank"]] + SUITS[card["suit"]]


class MatchAnalysis(Base):
    __tablename__ = "match_analyses"
    __table_args__ = (
        Index("match_analyses_player_recent", "player_id", desc("created_at")),
    )

    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    decisions: Mapped[int]
    accuracy: Mapped[float] = mapped_column(Double)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Decision(BaseModel):
    move: int
    situation: Situation
    played: str
    best: str
    played_rate: float
    best_rate: float

    @property
    def gap(self) -> float:
        return self.best_rate - self.played_rate


class SituationStats(BaseModel):
    decisions: int = 0
    mistakes: int = 0


class Analysis(BaseModel):
    decisions: int
    accuracy: float
    mistakes: list[Decision]
    situations: dict[Situation, SituationStats]


class Tip(BaseModel):
    move: int
    text: str
    source: Source


class Coaching(BaseModel):
    game_id: UUID
    decisions: int
    accuracy: float
    mistakes: list[Decision]
    situations: dict[Situation, SituationStats]
    tips: list[Tip]


TIPS: dict[Language, str] = {
    "en": "Move {move}: you played {played}, but {best} was safer ({best_pct}% vs {played_pct}%).",
    "ml": "നീക്കം {move}: നിങ്ങൾ {played} ഇട്ടു, പക്ഷേ {best} കൂടുതൽ സുരക്ഷിതമായിരുന്നു ({best_pct}% / {played_pct}%).",
    "ta": "நகர்வு {move}: நீங்கள் {played} போட்டீர்கள், ஆனால் {best} பாதுகாப்பானது ({best_pct}% / {played_pct}%).",
    "hi": "चाल {move}: आपने {played} चला, लेकिन {best} ज़्यादा सुरक्षित था ({best_pct}% / {played_pct}%)।",
    "kn": "ನಡೆ {move}: ನೀವು {played} ಆಡಿದಿರಿ, ಆದರೆ {best} ಹೆಚ್ಚು ಸುರಕ್ಷಿತವಾಗಿತ್ತು ({best_pct}% / {played_pct}%).",
    "te": "ఎత్తు {move}: మీరు {played} వేశారు, కానీ {best} మరింత సురక్షితం ({best_pct}% / {played_pct}%).",
}


def situation(view: dict[str, Any]) -> Situation:
    if len(view["hand"]) <= 2:
        return "near_escape"
    table = view["table"]
    if not table:
        return "leading"
    lead = table[0]["card"]["suit"]
    if any(card["suit"] == lead for card in view["legal_moves"]):
        return "following"
    return "cutting"


def analyse(replay: MatchReplay, seat: int, iterations: int = ITERATIONS) -> Analysis:
    """Score every real choice `seat` made. CPU bound; run it off the loop."""
    if replay.opening is None:
        raise AppError(
            404, "analysis_unavailable", "This match was played before analysis"
        )
    game = OnlineGame.restore(replay.opening)
    decisions: list[Decision] = []
    move = 0
    for batch in replay.events:
        for event in batch.events:
            if event.get("event") != "card_played":
                continue
            move += 1
            card = event["card"]
            if event["seat"] == seat:
                view = json.loads(game.view(seat))
                if len(view["legal_moves"]) >= 2:
                    scores = json.loads(game.evaluate(seat, iterations, seed=move))
                    best = scores[0]
                    chosen = next(
                        (score for score in scores if score["card"] == card), None
                    )
                    if chosen is not None:
                        decisions.append(
                            Decision(
                                move=move,
                                situation=situation(view),
                                played=label(card),
                                best=label(best["card"]),
                                played_rate=chosen["safe_rate"],
                                best_rate=best["safe_rate"],
                            )
                        )
            try:
                game.play(event["seat"], json.dumps(card))
            except ValueError as error:
                raise AppError(
                    409, "analysis_mismatch", "The replay does not match its deal"
                ) from error
    situations: dict[Situation, SituationStats] = {
        name: SituationStats() for name in SITUATIONS
    }
    for decision in decisions:
        stats = situations[decision.situation]
        stats.decisions += 1
        stats.mistakes += int(decision.gap >= MISTAKE_GAP)
    good = sum(decision.gap <= GOOD_GAP for decision in decisions)
    mistakes = sorted(
        (decision for decision in decisions if decision.gap >= MISTAKE_GAP),
        key=lambda decision: (-decision.gap, decision.move),
    )[:TOP_MISTAKES]
    return Analysis(
        decisions=len(decisions),
        accuracy=round(good / len(decisions), 3) if decisions else 1.0,
        mistakes=mistakes,
        situations=situations,
    )


def seat_of(replay: MatchReplay, player: UUID) -> int:
    for index, seat in enumerate(replay.seats):
        if seat.player_id == player and not seat.bot:
            return index
    raise AppError(404, "game_not_found", "Match replay not found")


async def stored_analysis(
    gateway: Gateway, replay: MatchReplay, player: UUID
) -> Analysis:
    async with gateway.platform.sessions() as db:
        row = await db.get(MatchAnalysis, (replay.id, player))
    if row is not None:
        return Analysis.model_validate(row.payload)
    seat = seat_of(replay, player)
    result = await asyncio.to_thread(analyse, replay, seat)
    async with gateway.platform.sessions.begin() as db:
        await db.execute(
            insert(MatchAnalysis)
            .values(
                game_id=replay.id,
                player_id=player,
                decisions=result.decisions,
                accuracy=result.accuracy,
                payload=result.model_dump(mode="json"),
            )
            .on_conflict_do_nothing()
        )
    return result


async def coaching(
    gateway: Gateway, replay: MatchReplay, player: UUID, language: Language
) -> Coaching:
    result = await stored_analysis(gateway, replay, player)
    cache = gateway.key(f"tips:{PROMPTS['tip'].label}:{replay.id}:{player}:{language}")
    redis = gateway.platform.redis
    if cached := await redis.get(cache):
        tips = [Tip.model_validate(item) for item in json.loads(cached)]
    else:
        tips = []
        for mistake in result.mistakes:
            fact = TIPS[language].format(
                move=mistake.move,
                played=mistake.played,
                best=mistake.best,
                best_pct=round(mistake.best_rate * 100),
                played_pct=round(mistake.played_rate * 100),
            )
            text, source = await reword(gateway, "tip", fact, language, words=40)
            tips.append(Tip(move=mistake.move, text=text, source=source))
        await redis.set(cache, json.dumps([tip.model_dump() for tip in tips]), ex=86400)
    return Coaching(game_id=replay.id, tips=tips, **result.model_dump())


async def recent_analyses(
    gateway: Gateway, player: UUID, limit: int = 20
) -> list[Analysis]:
    async with gateway.platform.sessions() as db:
        rows = await db.scalars(
            select(MatchAnalysis)
            .where(MatchAnalysis.player_id == player)
            .order_by(MatchAnalysis.created_at.desc())
            .limit(limit)
        )
        return [Analysis.model_validate(row.payload) for row in rows]
