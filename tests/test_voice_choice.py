import pytest
from fastapi.testclient import TestClient
from test_ai import FakeProvider
from test_online import TestGoogle, headers, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.main import create_app
from app.modules.ai.controllers import audio as ai_router
from app.modules.ai.schemas.commentary import Commentary
from app.modules.identity.schemas.profile import DEFAULT_VOICE, Profile, ProfileUpdate


def test_default_voice_follows_language_until_the_player_chooses():
    profile = Profile(
        id="00000000-0000-0000-0000-000000000001",
        display_name="A",
        language="ml",
        mmr=1200,
    )
    assert profile.commentary_voice == DEFAULT_VOICE["ml"]
    assert profile.model_copy(update={"voice": "aoede"}).commentary_voice == "aoede"
    with pytest.raises(ValueError):
        ProfileUpdate()


@pytest.mark.integration
def test_saved_voice_drives_commentary_audio_and_previews(settings, monkeypatch):
    used: list[str] = []

    class RecordingVoice:
        def __init__(self, gateway):
            pass

        async def clip(self, text, language, voice):
            used.append(voice)
            return b"RIFF....WAVE"

        async def enqueue(self, text, language, voice):
            return "pending"

    async def line(gateway, game_id, player_id, sequence, language):
        return Commentary(language=language, text="Vettu!", source="script"), True

    monkeypatch.setattr(ai_router, "Voice", RecordingVoice)
    monkeypatch.setattr(ai_router, "line", line)
    with TestClient(
        create_app(settings, TestGoogle(), FakeProvider()),
        base_url="https://testserver",
    ) as client:
        player = headers(sign_in(client))
        options = client.get("/api/v1/voices", headers=player).json()
        assert {option["id"] for option in options} == {"kore", "puck", "leda", "aoede"}
        assert [o["id"] for o in options if o["selected"]] == [DEFAULT_VOICE["ml"]]

        assert (
            client.patch("/api/v1/auth/me", json={}, headers=player).status_code == 422
        )
        updated = client.patch(
            "/api/v1/auth/me", json={"voice": "aoede"}, headers=player
        )
        assert updated.json()["voice"] == "aoede" and updated.json()["language"] == "ml"
        assert (
            client.patch(
                "/api/v1/auth/me", json={"voice": "robot"}, headers=player
            ).status_code
            == 422
        )

        game = "00000000-0000-0000-0000-000000000009"
        audio = client.get(f"/api/v1/games/{game}/commentary/3/voice", headers=player)
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
        client.get(
            f"/api/v1/games/{game}/commentary/3/voice?voice_id=puck", headers=player
        )
        preview = client.get("/api/v1/voices/leda/preview", headers=player)
        assert preview.status_code == 200
        assert used == ["aoede", "puck", "leda"]

        language = client.patch(
            "/api/v1/auth/me", json={"language": "en"}, headers=player
        )
        assert language.json()["voice"] == "aoede"  # changing language keeps the voice
