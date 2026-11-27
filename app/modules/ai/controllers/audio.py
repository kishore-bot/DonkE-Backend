from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path
from fastapi.responses import Response

from app.core.rate_limit import limit
from app.modules.ai.commentary import line
from app.modules.ai.dependencies import AI
from app.modules.ai.schemas import (
    Commentary,
    VoiceOption,
    VoiceStatus,
)
from app.modules.ai.voice import Voice
from app.modules.ai.voice import enabled as voice_enabled
from app.modules.identity.dependencies import CurrentPlayer
from app.modules.identity.schemas import DEFAULT_VOICE, VOICES, Language, VoiceId

router = APIRouter()

PREVIEW: dict[Language, str] = {
    "en": "Vettu! Seat two picks up the whole pile. What a moment!",
    "ml": "വെട്ട്! രണ്ടാം സീറ്റ് മുഴുവൻ ചീട്ടും എടുത്തു. എന്തൊരു നിമിഷം!",
    "ta": "வெட்டு! இரண்டாம் இருக்கை எல்லா அட்டைகளையும் எடுத்தது. என்ன ஒரு தருணம்!",
    "hi": "कट! सीट दो ने सारे पत्ते उठा लिए। क्या पल है!",
    "kn": "ಕತ್ತರಿಸು! ಎರಡನೇ ಆಸನ ಎಲ್ಲಾ ಎಲೆಗಳನ್ನು ತೆಗೆದುಕೊಂಡಿತು. ಎಂಥ ಕ್ಷಣ!",
    "te": "కట్! రెండో సీటు అన్ని కార్డులు తీసుకుంది. ఎంత మంచి క్షణం!",
}

Sequence = Annotated[int, Path(ge=1, le=1020)]


@router.get("/games/{game_id}/commentary/{sequence}")
async def commentary(
    game_id: UUID, sequence: Sequence, player: CurrentPlayer, gateway: AI
) -> Commentary:
    result, _ = await line(
        gateway, game_id, player.profile.id, sequence, player.profile.language
    )
    return result


@router.get(
    "/games/{game_id}/commentary/{sequence}/voice",
    response_model=VoiceStatus,
    responses={
        200: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def voice(
    game_id: UUID,
    sequence: Sequence,
    player: CurrentPlayer,
    gateway: AI,
    voice_id: VoiceId | None = None,
) -> Response | VoiceStatus:
    """Commentary audio in the player's language and saved voice.
    `voice_id` overrides the saved voice for this request."""
    result, finalized = await line(
        gateway, game_id, player.profile.id, sequence, player.profile.language
    )
    if not await voice_enabled(gateway):
        return VoiceStatus(status="disabled")
    if not finalized:
        return VoiceStatus(status="pending")
    chosen = voice_id or player.profile.commentary_voice
    voice = Voice(gateway)
    if audio := await voice.clip(result.text, result.language, chosen):
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    await limit(gateway.platform, "voice_request", str(player.profile.id), 30, 60)
    return VoiceStatus.model_validate(
        {"status": await voice.enqueue(result.text, result.language, chosen)}
    )


@router.get("/voices")
async def voices(player: CurrentPlayer) -> list[VoiceOption]:
    """The curated commentary voices and which one is selected."""
    selected = player.profile.commentary_voice
    return [
        VoiceOption(
            id=voice_id,
            label=label,
            style=style,
            default_for=[
                lang for lang, voice in DEFAULT_VOICE.items() if voice == voice_id
            ],
            selected=voice_id == selected,
        )
        for voice_id, (label, style) in VOICES.items()
    ]


@router.get(
    "/voices/{voice_id}/preview",
    response_model=VoiceStatus,
    responses={
        200: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def preview(
    voice_id: VoiceId, player: CurrentPlayer, gateway: AI
) -> Response | VoiceStatus:
    """A short sample line in the player's language. Poll until `ready`."""
    if not await voice_enabled(gateway):
        return VoiceStatus(status="disabled")
    language = player.profile.language
    voice = Voice(gateway)
    if audio := await voice.clip(PREVIEW[language], language, voice_id):
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=86400"},
        )
    await limit(gateway.platform, "voice_preview", str(player.profile.id), 12, 600)
    return VoiceStatus.model_validate(
        {"status": await voice.enqueue(PREVIEW[language], language, voice_id)}
    )
