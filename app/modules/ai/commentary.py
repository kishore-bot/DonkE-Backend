from hashlib import sha256
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.modules.ai.gateway import Gateway
from app.modules.ai.schemas import Commentary
from app.modules.identity.schemas import Language
from app.modules.matches import settlement
from app.modules.matches.repository import MatchRepository
from app.modules.matches.service import position

# Templates carry all game facts. Gemini may only choose a reaction from a fixed list.
MOMENTS = {
    "en": (
        "Seat {actor} cut. Seat {receiver} picked up {count} cards.",
        "Seat {actor} escaped.",
        "The match is over.",
    ),
    "ml": (
        "{actor}ാം സീറ്റ് വെട്ടി. {receiver}ാം സീറ്റ് {count} ചീട്ടെടുത്തു.",
        "{actor}ാം സീറ്റ് ഇറങ്ങി.",
        "കളി കഴിഞ്ഞു.",
    ),
    "ta": (
        "{actor}ஆம் இருக்கை வெட்டியது. {receiver}ஆம் இருக்கை {count} அட்டைகளை எடுத்தது.",
        "{actor}ஆம் இருக்கை வெளியேறியது.",
        "ஆட்டம் முடிந்தது.",
    ),
    "hi": (
        "सीट {actor} ने काटा। सीट {receiver} ने {count} पत्ते उठाए।",
        "सीट {actor} बाहर हो गई।",
        "खेल समाप्त हुआ।",
    ),
    "kn": (
        "ಆಸನ {actor} ಕತ್ತರಿಸಿತು. ಆಸನ {receiver} {count} ಎಲೆಗಳನ್ನು ತೆಗೆದುಕೊಂಡಿತು.",
        "ಆಸನ {actor} ಹೊರಬಂದಿತು.",
        "ಆಟ ಮುಗಿದಿದೆ.",
    ),
    "te": (
        "సీటు {actor} కట్ చేసింది. సీటు {receiver} {count} కార్డులు తీసుకుంది.",
        "సీటు {actor} బయటపడింది.",
        "ఆట ముగిసింది.",
    ),
}
REACTIONS = {
    "en": {"bright": "What a moment!", "calm": "Well played."},
    "ml": {"bright": "എന്തൊരു നിമിഷം!", "calm": "നന്നായി കളിച്ചു."},
    "ta": {"bright": "என்ன ஒரு தருணம்!", "calm": "நன்றாக விளையாடினீர்கள்."},
    "hi": {"bright": "क्या पल है!", "calm": "बहुत बढ़िया।"},
    "kn": {"bright": "ಎಂಥ ಕ್ಷಣ!", "calm": "ಚೆನ್ನಾಗಿ ಆಡಿದಿರಿ."},
    "te": {"bright": "ఎంత మంచి క్షణం!", "calm": "బాగా ఆడారు."},
}


async def public_events(
    gateway: Gateway, game_id: UUID, player_id: UUID, sequence: int
) -> list[dict[str, Any]]:
    repo = MatchRepository(gateway.platform)
    state = await repo.get(game_id)
    if state is not None:
        position(state, player_id)
        batches = await repo.events(game_id, sequence - 1, sequence)
    else:
        archive = await settlement.read_replay(gateway.platform, game_id, player_id)
        batches = [batch for batch in archive.events if batch.sequence == sequence]
    return [event for batch in batches for event in batch.events]


def moment(events: list[dict[str, Any]], language: Language) -> tuple[str, str]:
    templates = MOMENTS[language]
    cut = next((event for event in events if event["event"] == "vettu"), None)
    if cut is not None:
        return "vettu", templates[0].format(
            actor=cut["cutter"] + 1,
            receiver=cut["receiver"] + 1,
            count=len(cut["pile"]),
        )
    escaped = next(
        (event for event in events if event["event"] == "player_escaped"), None
    )
    if escaped is not None:
        return "escape", templates[1].format(actor=escaped["seat"] + 1)
    if any(event["event"] == "game_finished" for event in events):
        return "finished", templates[2]
    raise AppError(404, "commentary_not_found", "This turn has no commentary moment")


async def line(
    gateway: Gateway, game_id: UUID, player_id: UUID, sequence: int, language: Language
) -> Commentary:
    events = await public_events(gateway, game_id, player_id, sequence)
    kind, facts = moment(events, language)
    model = gateway.platform.settings.gemini_text_model
    digest = sha256(f"1:{game_id}:{sequence}:{language}:{model}".encode()).hexdigest()
    key = gateway.key(f"commentary:{digest}")
    redis = gateway.platform.redis
    if stored := await redis.get(key):
        return Commentary.model_validate_json(stored)
    plain = Commentary(language=language, text=facts, source="script")
    if gateway.provider is None:
        return plain
    if not await redis.set(key + ":lease", "1", nx=True, ex=10):
        return plain
    reaction = await gateway.select(
        "commentary",
        f"Choose bright or calm as a family-friendly reaction to this Kazhutha moment: {kind}.",
        set(REACTIONS[language]),
    )
    result = (
        Commentary(
            language=language,
            text=f"{facts} {REACTIONS[language][reaction]}",
            source="gemini",
        )
        if reaction
        else plain
    )
    await redis.set(key, result.model_dump_json(), ex=86400)
    return result
