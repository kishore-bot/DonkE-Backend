"""Rival bots remember every match against their player, and personas speak
in the player's language. Lines are written once per language: Gemini
translates the English line and the validator checks the script; English is
the fallback."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.helpers.prompts import PROMPTS
from app.modules.ai.helpers.rival_taunts import TAUNTS
from app.modules.ai.models.player_rival import PlayerRival
from app.modules.ai.schemas.rivals import PersonaLines, RivalView
from app.modules.ai.schemas.source import Source
from app.modules.ai.services.gateway import Gateway
from app.modules.ai.services.rewording import reword
from app.modules.identity.schemas.profile import Language
from app.modules.matches.helpers.bots import PERSONA_FLAVOR, PERSONAS, persona_for
from app.modules.matches.schemas.persona import Persona
from app.modules.matches.schemas.results import MatchReplay
from app.modules.progression.services.analytics import finishing_ranks, match_analytics


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
