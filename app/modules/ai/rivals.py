"""Rival bots remember every match against their player, and personas speak
in the player's language. Lines are written once per language: Gemini
translates the English line and the validator checks the script; English is
the fallback."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platform import Base
from app.modules.ai.gateway import Gateway
from app.modules.ai.prompts import PROMPTS, Source, reword
from app.modules.identity.schemas import Language
from app.modules.matches.bots import PERSONA_FLAVOR, PERSONAS, Persona, persona_for
from app.modules.matches.schemas import MatchReplay
from app.modules.progression.analytics import finishing_ranks, match_analytics


class PlayerRival(Base):
    __tablename__ = "player_rivals"

    player_id: Mapped[UUID] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    persona: Mapped[str] = mapped_column(String(20))
    games: Mapped[int] = mapped_column(server_default="0")
    wins: Mapped[int] = mapped_column(server_default="0")
    losses: Mapped[int] = mapped_column(server_default="0")


async def record(db: AsyncSession, replay: MatchReplay) -> None:
    """After settlement: did each rival's player finish ahead of it?"""
    rivals = [
        (index, seat)
        for index, seat in enumerate(replay.seats)
        if seat.rival_of is not None and seat.persona is not None
    ]
    if not rivals:
        return
    ranks = finishing_ranks(match_analytics(replay))
    for index, seat in rivals:
        owner = next(
            (
                position
                for position, other in enumerate(replay.seats)
                if other.player_id == seat.rival_of
            ),
            None,
        )
        if owner is None or seat.rival_of is None:
            continue
        won = ranks[owner] < ranks[index]
        lost = ranks[owner] > ranks[index]
        query = insert(PlayerRival).values(
            player_id=seat.rival_of,
            persona=seat.persona,
            games=1,
            wins=int(won),
            losses=int(lost),
        )
        await db.execute(
            query.on_conflict_do_update(
                index_elements=[PlayerRival.player_id],
                set_={
                    "games": PlayerRival.games + 1,
                    "wins": PlayerRival.wins + int(won),
                    "losses": PlayerRival.losses + int(lost),
                },
            )
        )


class RivalView(BaseModel):
    persona: Persona
    name: str
    games: int
    wins: int
    losses: int
    taunt: str
    source: Source


TAUNTS: dict[Language, str] = {
    "en": "{name} here. You have beaten me {wins} times and lost {losses}. Round {next} is mine!",
    "ml": "ഞാൻ {name}. നീ എന്നെ {wins} തവണ തോൽപ്പിച്ചു, {losses} തവണ തോറ്റു. {next}-ാം റൗണ്ട് എന്റേതാണ്!",
    "ta": "நான் {name}. நீ என்னை {wins} முறை வென்றாய், {losses} முறை தோற்றாய். {next}-வது சுற்று என்னுடையது!",
    "hi": "मैं {name} हूँ। तुमने मुझे {wins} बार हराया और {losses} बार हारे। राउंड {next} मेरा है!",
    "kn": "ನಾನು {name}. ನೀನು ನನ್ನನ್ನು {wins} ಬಾರಿ ಸೋಲಿಸಿದೆ, {losses} ಬಾರಿ ಸೋತೆ. {next}ನೇ ಸುತ್ತು ನನ್ನದು!",
    "te": "నేను {name}. నువ్వు నన్ను {wins} సార్లు ఓడించావు, {losses} సార్లు ఓడిపోయావు. {next}వ రౌండ్ నాదే!",
}


async def rival(gateway: Gateway, player: UUID, language: Language) -> RivalView:
    async with gateway.platform.sessions() as db:
        row = await db.get(PlayerRival, player)
    persona = persona_for(player)
    games, wins, losses = (row.games, row.wins, row.losses) if row else (0, 0, 0)
    name = PERSONAS[persona]
    fact = TAUNTS[language].format(name=name, wins=wins, losses=losses, next=games + 1)
    cache = gateway.key(
        f"rival:{PROMPTS['rival'].label}:{player}:{language}:{games}:{wins}"
    )
    redis = gateway.platform.redis
    cached = await redis.get(cache)
    if cached:
        text = cached.decode() if isinstance(cached, bytes) else cached
        source: Source = "gemini"
    else:
        text, source = await reword(
            gateway, "rival", fact, language, words=35, keep=(name,), name=name
        )
        if source == "gemini":
            await redis.set(cache, text, ex=7 * 86400)
    return RivalView(
        persona=persona,
        name=name,
        games=games,
        wins=wins,
        losses=losses,
        taunt=text,
        source=source,
    )


class PersonaLines(BaseModel):
    language: Language
    personas: dict[Persona, dict[str, str]]
    source: Source


async def persona_lines(gateway: Gateway, language: Language) -> PersonaLines:
    """Localized persona reaction lines, keyed like `persona_line` events."""
    if language == "en":
        return PersonaLines(language="en", personas=PERSONA_FLAVOR, source="template")
    cache = gateway.key(f"persona-lines:{PROMPTS['translate'].label}:{language}")
    redis = gateway.platform.redis
    if cached := await redis.get(cache):
        return PersonaLines.model_validate_json(cached)
    personas: dict[Persona, dict[str, str]] = {}
    complete = True
    for persona, lines in PERSONA_FLAVOR.items():
        personas[persona] = {}
        for key, english in lines.items():
            text, source = await reword(
                gateway, "translate", english, language, words=25
            )
            complete &= source == "gemini"
            personas[persona][key] = text
    result = PersonaLines(
        language=language,
        personas=personas,
        source="gemini" if complete else "template",
    )
    if complete:
        await redis.set(cache, result.model_dump_json(), ex=30 * 86400)
    return result
