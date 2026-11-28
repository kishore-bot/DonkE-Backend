import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from test_admin_console import admin_login
from test_ai import FakeProvider
from test_online import TestGoogle
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.ai.dto.provider import Written
from app.modules.ai.services.gateway import Gateway
from app.modules.ai.services.voice import Voice
from app.modules.story.models.season_cue import SeasonCue


@pytest.mark.integration
def test_season_cue_checkpoints_review_and_japanese_audio_fallback(settings):
    class Provider(FakeProvider):
        drafts = 0

        async def write(self, task, prompt):
            self.drafts += 1
            text = "I held my ground." if self.drafts == 1 else "ここで踏ん張った。"
            return Written(text, 10)

    provider = Provider()
    pack, character = "grimoire-awakening-v1", "stormscribe"
    public = f"/api/v1/story/cues/{pack}/{character}/victory"
    admin = "/api/v1/admin/season-cues"

    async def clean():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            await db.execute(
                delete(SeasonCue).where(
                    SeasonCue.pack_key == pack, SeasonCue.character_id == character
                )
            )

    try:
        with TestClient(
            create_app(settings, TestGoogle(), provider), base_url="https://testserver"
        ) as client:
            assert client.get(public).status_code == 404
            _, csrf = admin_login(client, settings)
            created = client.post(
                admin,
                headers=csrf,
                json={
                    "pack_key": pack,
                    "character_id": character,
                    "moment": "victory",
                    "reason": "Test cue",
                },
            )
            assert created.status_code == 200, created.text
            cue = created.json()
            advance = f"{admin}/{cue['id']}/advance"
            draft = {"stage": "english", "reason": "Draft first locale"}
            first = client.post(advance, headers=csrf, json=draft)
            assert first.json()["stage"] == "japanese"
            assert client.post(advance, headers=csrf, json=draft).json() == first.json()
            assert provider.drafts == 1

        with TestClient(
            create_app(settings, TestGoogle(), provider), base_url="https://testserver"
        ) as client:
            _, csrf = admin_login(client, settings)
            translated = client.post(
                advance,
                headers=csrf,
                json={"stage": "japanese", "reason": "Resume translation"},
            )
            assert translated.json()["stage"] == "review"
            assert translated.json()["ja_source"] == "gemini"
            assert client.get(public).status_code == 404
            review = client.post(
                advance,
                headers=csrf,
                json={
                    "stage": "review",
                    "en": "I made it through!",
                    "reason": "Approve edited dialogue",
                },
            )
            assert review.json()["stage"] == "published"
            assert review.json()["en_source"] == "editor"
            assert client.get(public).json()["audio_locale"] is None

            async def verify_audio():
                async with open_platform(settings) as platform:
                    voice = Voice(Gateway(platform, provider))
                    assert await voice.tick()
                    assert await voice.tick()
                    await platform.redis.delete(
                        voice.gateway.key(
                            f"media:voice:clip:{voice.identifier('I made it through!', 'en', 'puck')}"
                        )
                    )

            asyncio.run(verify_audio())
            cue = client.get(public).json()
            assert cue["caption"] == "I made it through!"
            assert cue["audio_locale"] == "ja"
            assert (
                client.get(public + "/audio/ja").headers["content-type"] == "audio/wav"
            )
            assert client.get(public + "/audio/en").status_code == 404
    finally:
        asyncio.run(clean())
