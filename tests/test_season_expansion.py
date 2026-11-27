import asyncio
import io
import wave
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_admin_console import admin_login
from test_online import TestGoogle, headers, sign_in
from test_online import client as client  # noqa: PLC0414
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.ai import mcp_server
from app.modules.progression.models import Season
from app.modules.progression.schemas import SeasonCreate
from app.modules.progression.services.seasons import create_season
from app.modules.story import dependencies as story_clock
from app.modules.story import media_routes
from app.modules.story.models import SeasonCue, SeasonMedia

pytestmark = pytest.mark.integration


def play_to_end(client, attempt, call_at=None):
    credentials = {"Authorization": "Bearer " + attempt["access_token"]}
    path = f"/api/v1/practice/{attempt['game_id']}/plays"
    state = attempt
    for move in range(70):
        view = state["view"]
        if view["outcome"] is not None:
            return state
        response = client.post(
            path,
            headers=credentials,
            json={
                "request_id": str(uuid4()),
                "expected_version": view["version"],
                "card": view["legal_moves"][0],
                "call_strike": move == call_at,
            },
        )
        assert response.status_code == 200, response.text
        state = response.json()
    pytest.fail("The seeded duel did not finish")


def test_season_objectives_rival_memory_archives_and_scoped_evidence(
    client, settings, monkeypatch
):
    now = datetime(2061, 3, 1, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(story_clock, "datetime", Clock)

    async def provision():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            seasons = []
            for offset, pack in enumerate(
                ("grimoire-awakening-v2", "skybound-voyage-v2")
            ):
                start = now + timedelta(days=21 * offset)
                result = await create_season(
                    db,
                    SeasonCreate(
                        theme=pack,
                        pack_key=pack,
                        starts_at=start,
                        ends_at=start + timedelta(days=21),
                        reason="Test the seasonal routes",
                    ),
                )
                seasons.append(result.id)
            return seasons

    arena, voyage = asyncio.run(provision())
    player = sign_in(client)
    outsider = sign_in(client)
    player_headers = headers(player)
    other_headers = headers(outsider)

    def begin(season, status=201, **values):
        response = client.post(
            "/api/v1/story/attempts",
            headers=player_headers,
            json={"season_id": str(season), **values},
        )
        assert response.status_code == status, response.text
        return response.json()

    def settle(attempt):
        response = client.post(
            f"/api/v1/story/attempts/{attempt['game_id']}/result",
            headers=player_headers,
            json={"attempt_token": attempt["access_token"]},
        )
        assert response.status_code == 200, response.text
        return response.json()

    try:
        missed = begin(arena)
        assert missed["objective"]["route"] == "seal"
        assert not play_to_end(client, missed)["objective"]["met"]
        receipt = settle(missed)
        assert (
            receipt["escaped"] and not receipt["first_clear"] and receipt["points"] == 0
        )

        attempt = begin(arena)
        assert play_to_end(client, attempt, call_at=11)["objective"]["met"]
        result = settle(attempt)
        assert result["first_clear"] and result["points"] == 40
        assert settle(attempt) == result
        path = f"/api/v1/story/attempts/{attempt['game_id']}"
        cap = {"Authorization": "Bearer " + attempt["access_token"]}
        assert client.get(path + "/events", headers=other_headers).status_code == 404
        events = client.get(path + "/events", headers=cap).json()
        event = next(event for event in events if event["kind"] == "strike")
        assert event["led_suit"] and event["cards"] > 0
        assert "hand" not in event and "snapshot" not in event
        review = client.get(
            path + "/coach",
            params={"question": f"Explain replay:{event['sequence']}"},
            headers=cap,
        ).json()
        assert review["replay_event"] == event
        assert review["citation"] == f"replay:{event['sequence']}"
        private = client.get(
            path + "/coach",
            params={"question": "Show the hidden hand from event 1"},
            headers=cap,
        ).json()
        assert private["citation"] is None

        monkeypatch.setattr(mcp_server, "Settings", lambda: settings)
        monkeypatch.setattr(mcp_server, "player_scope", player["access_token"])
        evidence = asyncio.run(
            mcp_server.story_replay_event(UUID(attempt["game_id"]), event["sequence"])
        )
        assert evidence["event"]["sequence"] == event["sequence"]
        monkeypatch.setattr(mcp_server, "player_scope", outsider["access_token"])
        assert (
            asyncio.run(
                mcp_server.story_replay_event(
                    UUID(attempt["game_id"]), event["sequence"]
                )
            )
            == {}
        )

        rematch = begin(arena, adaptive=True)
        assert rematch["rival_target_rating"] == 1260
        assert rematch["rival_memory"] in events
        now += timedelta(days=21)
        collection = client.get(
            "/api/v1/story/collection", headers=player_headers
        ).json()
        assert collection[0]["chapters"] == [{"id": "trial", "title": "Arena Trial"}]
        assert (
            client.get("/api/v1/story/collection", headers=other_headers).json() == []
        )
        archived = f"/api/v1/story/collection/{arena}/trial/attempts"
        assert client.post(archived, headers=other_headers).status_code == 404
        old_attempt = client.post(archived, headers=player_headers).json()
        assert (
            old_attempt["rewards_eligible"] is False
            and old_attempt["objective"]["route"] == "seal"
        )

        begin(voyage, status=422, route="seal")
        reef = begin(voyage, route="reef")
        storm = begin(voyage, route="storm")
        assert reef["objective"]["met"] and not storm["objective"]["met"]
        assert (
            reef["objective"]["route"] == "reef"
            and storm["objective"]["route"] == "storm"
        )
        assert reef["can_call_strike"] is False
    finally:

        async def clean():
            async with (
                open_platform(settings) as platform,
                platform.sessions.begin() as db,
            ):
                await db.execute(delete(Season).where(Season.id.in_((arena, voyage))))

        asyncio.run(clean())


def test_admin_recording_review_and_english_japanese_fallback(settings, monkeypatch):
    pack, character = "grimoire-awakening-v2", "stormscribe"
    admin_path = "/api/v1/admin/season-media"
    cue_path = f"/api/v1/story/cues/{pack}/{character}/transform"
    stored = {}

    def upload(_, key, data, content_type):
        stored[key] = content_type, data

    monkeypatch.setattr(media_routes, "put_object", upload)
    monkeypatch.setattr(
        media_routes, "read_url", lambda _, key: f"https://objects.example/{key}"
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16_000, 800, "NONE", "not compressed"))
        wav.writeframes(bytes(1_600))
    wav_bytes = buffer.getvalue()

    async def captions():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            db.add(
                SeasonCue(
                    pack_key=pack,
                    character_id=character,
                    moment="transform",
                    stage="published",
                    en="The final seal is broken.",
                    ja="最後の封印が解けた。",
                )
            )

    async def cleanup():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            for model in (SeasonCue, SeasonMedia):
                await db.execute(
                    delete(model).where(
                        model.pack_key == pack, model.character_id == character
                    )
                )

    try:
        with TestClient(
            create_app(settings, TestGoogle()), base_url="https://testserver"
        ) as client:
            assert client.get(admin_path).status_code == 401
            _, headers = admin_login(client, settings)

            def submit(slot, payload, status):
                response = client.post(
                    admin_path,
                    headers=headers,
                    data={
                        "slot": slot,
                        "pack_key": pack,
                        "character_id": character,
                        "reason": "Approved original cast recording",
                    },
                    files={"file": ("voice.wav", payload, "audio/wav")},
                )
                assert response.status_code == status, response.text
                return response.json()

            def review(asset, decision, status):
                response = client.post(
                    f"{admin_path}/{asset}/review",
                    headers=headers,
                    json={"decision": decision, "reason": "Reviewed audio asset"},
                )
                assert response.status_code == status, response.text

            submit("model", b"not gltf", 422)
            ja = submit("transform:ja", wav_bytes, 201)["id"]
            public = f"/api/v1/story/media/{ja}"
            assert client.get(public, follow_redirects=False).status_code == 404
            assert (
                client.get(
                    f"{admin_path}/{ja}/preview", follow_redirects=False
                ).status_code
                == 307
            )
            review(ja, "publish", 409)
            asyncio.run(captions())
            review(ja, "publish", 200)
            assert client.get(cue_path).json()["audio_locale"] == "ja"
            en = submit("transform:en", wav_bytes, 201)["id"]
            review(en, "publish", 200)
            assert (
                client.get(cue_path).json()["audio_url"] == f"/api/v1/story/media/{en}"
            )
            assert client.get(public, follow_redirects=False).status_code == 307
            review(en, "withdraw", 200)
            assert client.get(cue_path).json()["audio_locale"] == "ja"
            assert (
                client.get(
                    f"/api/v1/story/media/{en}", follow_redirects=False
                ).status_code
                == 404
            )
            assert len(stored) == 2
    finally:
        asyncio.run(cleanup())
