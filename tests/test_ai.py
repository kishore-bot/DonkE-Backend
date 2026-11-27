import asyncio
import io
import wave
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.main import create_app
from app.modules.admin.service import AdminService
from app.modules.ai import commentary
from app.modules.ai.controllers.audio import voice as request_voice
from app.modules.ai.gateway import Gateway
from app.modules.ai.knowledge import NO_MATCH, sources
from app.modules.ai.provider import Selected
from app.modules.ai.schemas import VoiceStatus
from app.modules.ai.voice import Voice
from app.modules.identity.schemas import Profile
from app.modules.identity.service import Principal
from app.modules.matches.schemas import EventBatch, GameSeat, MatchReplay
from app.modules.matches.settlement import persist


class FakeProvider:
    def __init__(self):
        self.choices = []
        self.voice_calls = 0

    async def select(self, task, prompt):
        self.choices.append(task)
        return Selected("unknown" if task == "commentary" else "vettu", 12)

    async def render(self, text, voice):
        self.voice_calls += 1
        output = io.BytesIO()
        with wave.open(output, "wb") as file:
            file.setparams((1, 2, 24000, 1, "NONE", ""))
            file.writeframes(b"\0\0")
        return output.getvalue()

    async def embed(self, texts, *, query):
        results = []
        for index, _ in enumerate(texts):
            row = [0.0] * 768
            row[2 if query else index] = 1.0
            results.append(row)
        return results


def test_curated_native_rule_retrieval():
    assert sources("വെട്ട്")[0].source == "vettu"
    assert sources("do tomatoes grow on trees") == []


@pytest.mark.integration
def test_commentary_quota_is_shared_with_voice_and_does_not_limit_other_players(
    settings, monkeypatch
):
    async def public_events(*args):
        return [{"event": "game_finished"}]

    monkeypatch.setattr(commentary, "public_events", public_events)
    config = settings.model_copy(update={"ai_text_daily_calls": 5})

    async def check():
        async with open_platform(config) as platform:
            provider = FakeProvider()
            gateway = Gateway(platform, provider)
            player = Principal(
                Profile(id=uuid4(), display_name="Player", language="en", mmr=1200),
                uuid4(),
            )
            first, second = uuid4(), uuid4()
            await commentary.line(gateway, first, player.profile.id, 1, "en")
            assert await request_voice(first, 1, player, gateway) == VoiceStatus(
                status="pending"
            )
            with pytest.raises(AppError) as caught:
                await request_voice(second, 1, player, gateway)
            assert caught.value.status == 429
            await commentary.line(gateway, second, uuid4(), 1, "en")
            assert provider.choices == ["commentary", "commentary"]

    asyncio.run(check())


@pytest.mark.integration
def test_coach_uses_localized_rules_and_no_match_messages(settings):
    with TestClient(create_app(settings, TestGoogle())) as client:
        player = headers(sign_in(client))
        for language, query in [
            ("ta", "வெட்டு"),
            ("hi", "वेट्टू"),
            ("kn", "ವೆಟ್ಟು"),
            ("te", "వెట్టు"),
        ]:
            assert (
                client.patch(
                    "/api/v1/auth/me", headers=player, json={"language": language}
                ).status_code
                == 200
            )
            response = client.post(
                "/api/v1/coach/ask", headers=player, json={"question": query}
            )
            assert response.json()["citation"] == "vettu"
            assert response.json()["answer"] == sources(query)[0].translations[language]
            missing = client.post(
                "/api/v1/coach/ask", headers=player, json={"question": "tomatoes"}
            )
            assert missing.json()["answer"] == NO_MATCH[language]


@pytest.mark.integration
def test_voice_waits_for_final_commentary_before_queueing(settings, monkeypatch):
    async def public_events(*args):
        return [{"event": "game_finished"}]

    monkeypatch.setattr(commentary, "public_events", public_events)

    async def concurrent_requests():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowProvider(FakeProvider):
            async def select(self, task, prompt):
                started.set()
                await release.wait()
                return Selected("bright")

        provider = SlowProvider()
        principal = Principal(
            Profile(id=uuid4(), display_name="Player", language="en", mmr=1200),
            uuid4(),
        )
        game = uuid4()
        async with open_platform(settings) as platform:
            gateway = Gateway(platform, provider)
            first = asyncio.create_task(request_voice(game, 1, principal, gateway))
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                waiting = await request_voice(game, 1, principal, gateway)
                assert waiting == VoiceStatus(status="pending")
                queue = gateway.key("media:voice:queue")
                assert await platform.redis.zcard(queue) == 0
            finally:
                release.set()
                result = await first
            assert result == VoiceStatus(status="pending")
            assert await platform.redis.zcard(queue) == 1
            worker = Voice(gateway)
            assert await worker.tick()
            assert not await worker.tick()
            response = await request_voice(game, 1, principal, gateway)
            assert response.headers["content-type"] == "audio/wav"
            assert provider.voice_calls == 1

    asyncio.run(concurrent_requests())


@pytest.mark.integration
def test_commentary_preserves_facts_and_voice_cache(settings):
    fake = FakeProvider()
    with TestClient(
        create_app(settings, TestGoogle(), fake), base_url="https://testserver"
    ) as client:
        token = sign_in(client)
        user = headers(token)
        player = UUID(profile(client, token)["id"])
        game_id = uuid4()

        async def archive():
            async with open_platform(settings) as platform:
                await persist(
                    platform,
                    MatchReplay(
                        id=game_id,
                        room_id=uuid4(),
                        mode=None,
                        outcome={"reason": "all_safe"},
                        seats=[
                            GameSeat(
                                player_id=player,
                                display_name="Name",
                                ready=True,
                                bot=False,
                            )
                        ],
                        events=[
                            EventBatch(
                                sequence=2,
                                events=[
                                    {
                                        "event": "vettu",
                                        "cutter": 0,
                                        "receiver": 1,
                                        "pile": [{}, {}, {}],
                                    },
                                ],
                            )
                        ],
                    ),
                )

        asyncio.run(archive())
        path = f"/api/v1/games/{game_id}/commentary/2"
        line = client.get(path, headers=user).json()
        assert line["language"] == "ml"
        assert line["source"] == "script"
        assert "3" in line["text"]
        assert client.get(path + "/voice", headers=user).json() == {"status": "pending"}

        async def worker():
            async with open_platform(settings) as platform:
                voice = Voice(Gateway(platform, fake))
                assert await voice.tick()
                assert not await voice.tick()

        asyncio.run(worker())
        clip = client.get(path + "/voice", headers=user)
        assert clip.headers["content-type"] == "audio/wav"
        assert clip.content.startswith(b"RIFF")
        assert fake.voice_calls == 1
        assert fake.choices == ["commentary"]
        outsider = headers(sign_in(client))
        assert client.get(path, headers=outsider).status_code == 404


@pytest.mark.integration
def test_hybrid_coach_and_audited_operator_usage(settings):
    fake = FakeProvider()
    with TestClient(
        create_app(settings, TestGoogle(), fake), base_url="https://testserver"
    ) as client:
        user = headers(sign_in(client))

        async def account():
            async with open_platform(settings) as platform:
                return await AdminService(platform).create_account(
                    "ai-" + uuid4().hex[:8], "synthetic-ai-test", "admin", uuid4()
                )

        admin = asyncio.run(account())
        login = client.post(
            "/api/v1/admin/auth/login",
            json={"username": admin.username, "password": "synthetic-ai-test"},
        ).json()
        index = client.post(
            "/api/v1/admin/ai/reindex",
            json={"reason": "Index rule fixtures"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert index.status_code == 200, index.text
        assert index.json()["indexed"] == 6
        reply = client.post(
            "/api/v1/coach/ask", json={"question": "unknown description"}, headers=user
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["citation"] == "vettu"
        assert reply.json()["source"] == "gemini_selected"
        usage = client.get("/api/v1/admin/ai/usage").json()
        assert (
            usage["embedding_index_calls"]
            == usage["embedding_query_calls"]
            == usage["coach_calls"]
            == 1
        )
        assert usage["coach_tokens"] == 12


@pytest.mark.integration
def test_coach_uses_script_when_daily_budget_is_zero(settings):
    fake = FakeProvider()
    config = settings.model_copy(update={"ai_text_daily_calls": 0})
    with TestClient(create_app(config, TestGoogle(), fake)) as client:
        user = headers(sign_in(client))
        answer = client.post(
            "/api/v1/coach/ask", json={"question": "Vettu"}, headers=user
        ).json()
        assert answer["citation"] == "vettu"
        assert answer["source"] == "rules"
        assert fake.choices == []


@pytest.mark.integration
def test_voice_recovers_expired_lease_and_ignores_stale_owner(settings):
    async def recover():
        fake = FakeProvider()
        async with open_platform(settings) as platform:
            gateway = Gateway(platform, fake)
            service = Voice(gateway)
            message = "Well played."
            assert await service.enqueue(message, "en", "kore") == "pending"
            claimed = await service.execute("claim", owner="old", concurrency=2)
            identifier = claimed["id"]
            await platform.redis.delete(gateway.key(f"media:voice:lease:{identifier}"))
            await platform.redis.zadd(gateway.key("media:voice:queue"), {identifier: 0})
            await platform.redis.zadd(
                gateway.key("media:voice:active"), {identifier: 0}
            )
            assert (await service.execute("claim", owner="current", concurrency=2))[
                "id"
            ] == identifier
            await service.execute("complete", id=identifier, owner="old", clip="stale")
            assert await service.clip(message, "en", "kore") is None
            await service.execute("retry", id=identifier, owner="current")
            await platform.redis.zadd(gateway.key("media:voice:queue"), {identifier: 0})
            assert await service.tick()
            assert await service.clip(message, "en", "kore") is not None
            assert not await service.tick()

    asyncio.run(recover())


def test_pydantic_ai_selection_through_the_gemini_adapter():
    from pydantic_ai.models.test import TestModel

    from app.core.config import Settings
    from app.modules.ai.provider import Gemini

    async def select():
        gemini = Gemini(Settings(gemini_api_key="synthetic-test-model"))
        try:
            with gemini.coach.override(
                model=TestModel(
                    custom_output_text='{"key": "vettu"}',
                    profile={"supports_json_schema_output": True},
                )
            ):
                assert (await gemini.select("coach", "Choose vettu")).key == "vettu"
        finally:
            await gemini.close()

    asyncio.run(select())
