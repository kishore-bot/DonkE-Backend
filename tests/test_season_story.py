import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.ai.dto.provider import Selected
from app.modules.progression.helpers import clock as season_routes
from app.modules.progression.helpers.calendar import week_start
from app.modules.progression.models.season import Season
from app.modules.progression.models.season_day import SeasonDay
from app.modules.progression.models.season_player import SeasonPlayer
from app.modules.progression.repositories.economy import streak_stars
from app.modules.progression.schemas.seasons import SeasonCreate
from app.modules.progression.services.seasons import create_season
from app.modules.story import dependencies as story_clock


@pytest.mark.integration
def test_seeded_story_call_first_clear_and_final_form(client, settings, monkeypatch):
    start = datetime(2038, 7, 1, tzinfo=UTC)
    end = start + timedelta(days=21)
    now = start + timedelta(days=20)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(story_clock, "datetime", Clock)
    monkeypatch.setattr(season_routes, "datetime", Clock)

    async def arrange():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            return await create_season(
                db,
                SeasonCreate(
                    theme="Story test",
                    starts_at=start,
                    ends_at=end,
                    pack_key="grimoire-awakening-v1",
                    reason="Seeded story test",
                ),
            )

    season = asyncio.run(arrange())
    tokens = sign_in(client)
    player = UUID(profile(client, tokens)["id"])
    auth, other = headers(tokens), headers(sign_in(client))
    base = f"/api/v1/seasons/{season.id}/me"
    path = f"{base}/awakening/path"
    pending = "/api/v1/story/awakening/pending"

    async def prepare_points():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            row = await db.get(SeasonPlayer, (season.id, player))
            assert row is not None
            row.points = 300
            stored = await db.get(Season, season.id)
            assert stored is not None
            for day, act in ((0, 0), (6, 0), (7, 7), (13, 7), (14, 14), (20, 14)):
                assert (
                    week_start(start + timedelta(days=day), stored)
                    == (start + timedelta(days=act)).date()
                )
            db.add_all(
                [
                    SeasonDay(
                        season_id=season.id,
                        player_id=player,
                        day=(start + timedelta(days=offset)).date(),
                    )
                    for offset in (0, 1, 2, 3, 4, 6, 7)
                ]
            )
            await db.flush()
            assert await streak_stars(db, season.id, player) == 1

    async def clean():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            await db.execute(delete(Season).where(Season.id == season.id))

    try:
        assert client.get(path).status_code == 401
        assert client.get(pending).status_code == 401
        assert client.get(pending, headers=auth).json() is None
        response = client.get(path, headers=auth)
        path_start = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert path_start["missing"] == [
            "choose_character",
            "clear_duel",
            "earn_points",
        ]
        assert path_start["claim_available"] is False
        assert path_start["steps"][0]["id"] == "season_active"
        assert path_start["steps"][-1]["requires"] == ["claim_form"]
        assert (client.get(path, headers=other).json()["character_id"]) is None
        assert (
            client.put(
                f"{base}/character", json={"character_id": "ashblade"}, headers=auth
            ).status_code
            == 200
        )
        start_path = "/api/v1/story/attempts"
        guest = client.post(start_path, json={"season_id": str(season.id)}).json()
        attempt = client.post(
            start_path, json={"season_id": str(season.id)}, headers=auth
        ).json()
        assert attempt["view"] == guest["view"]
        assert attempt["character"]["id"] == "ashblade"
        assert guest["rewards_eligible"] is False

        class RivalProvider:
            async def select(self, task, prompt):
                assert task == "story_rival"
                assert "The Arena Keeper" in prompt
                return Selected("pressure")

        with monkeypatch.context() as fake:
            fake.setattr(client.app.state.gateway, "provider", RivalProvider())
            adaptive = client.post(
                start_path, json={"season_id": str(season.id), "adaptive": True}
            )
            assert adaptive.status_code == 201
            attempt_data = adaptive.json()
            trial = client.app.state.practice.repository.get(
                UUID(attempt_data["game_id"]), attempt_data["access_token"]
            )
            assert trial.story.intent == "pressure"
            assert trial.story.intent_source == "gemini"

        turn_path = f"/api/v1/practice/{attempt['game_id']}/plays"
        result_path = f"/api/v1/story/attempts/{attempt['game_id']}/result"
        result_request = {"attempt_token": attempt["access_token"]}
        capability = {"Authorization": f"Bearer {attempt['access_token']}"}
        assert (
            client.post(result_path, json=result_request, headers=other).status_code
            == 404
        )
        assert (
            client.post(result_path, json=result_request, headers=auth).status_code
            == 409
        )
        coach_path = f"/api/v1/story/attempts/{attempt['game_id']}/coach"
        assert client.get(coach_path, headers=capability).status_code == 409
        share_path = f"/api/v1/story/attempts/{attempt['game_id']}/share"
        assert client.post(share_path, headers=capability).status_code == 409

        saw_success = False
        move = 0
        while attempt["view"]["outcome"] is None:
            assert move < 50
            command = {
                "request_id": str(uuid4()),
                "expected_version": attempt["view"]["version"],
                "card": attempt["view"]["legal_moves"][0],
                "call_strike": move == 5,
            }
            played = client.post(turn_path, json=command, headers=capability)
            assert played.status_code == 200, played.text
            attempt = played.json()
            if move == 5:
                assert attempt["events"][0]["event"] == "strike_called"
                assert (
                    client.post(turn_path, json=command, headers=capability).json()
                    == attempt
                )
            saw_success |= any(
                event["event"] == "strike_call_resolved" and event["success"]
                for event in attempt["events"]
            )
            move += 1
        assert saw_success and 0 in attempt["view"]["escape_order"]
        assert client.get(coach_path, headers=other).status_code == 404
        evidence = client.get(coach_path, headers=capability).json()
        assert evidence["citation"] == "rival-first-choice"
        assert evidence["evidence"]["candidate_count"] >= 2
        assert set(evidence["evidence"]) == {
            "intent",
            "source",
            "card",
            "candidate_count",
            "played_safe_rate",
            "best_safe_rate",
        }
        answer = client.get(
            coach_path, headers=capability, params={"question": "What is a Strike?"}
        ).json()
        assert answer["citation"] == "rule:vettu"
        assert (
            client.get(
                coach_path, headers=capability, params={"question": "tomato gardening"}
            ).json()["citation"]
            is None
        )

        now = end + timedelta(minutes=1)
        assert client.post(share_path, headers=other).status_code == 404
        shared = client.post(share_path, headers=capability)
        assert shared.status_code == 200
        code = shared.json()["code"]
        challenge_path = f"/api/v1/story/challenges/{code}"
        card = client.get(challenge_path).json()
        assert card["result"] == {"escaped": True, "plays": attempt["view"]["version"]}
        assert set(card) == {"pack_title", "rival", "character", "result", "expires_at"}
        bad = f"/api/v1/story/challenges/invalid.{code.split('.', 1)[1]}"
        assert client.get(bad).status_code == 404
        replay = client.post(challenge_path + "/attempts", headers=other)
        assert replay.status_code == 201, replay.text
        replay = replay.json()
        assert replay["view"] == guest["view"]
        assert replay["game_id"] != guest["game_id"]
        assert replay["access_token"] != result_request["attempt_token"]
        assert replay["rewards_eligible"] is False

        for _ in range(2):
            assert client.post(
                result_path, json=result_request, headers=auth
            ).json() == {
                "escaped": True,
                "first_clear": True,
                "coins": 20,
                "points": 40,
            }
        assert client.get("/api/v1/store/wallet", headers=auth).json() == {"coins": 20}
        assert client.get(f"{base}/story", headers=auth).json()["points"] == 40
        assert client.get(f"{base}/story", headers=auth).json()["missing"] == [
            "earn_points"
        ]

        assert client.post(f"{base}/awakening", headers=auth).status_code == 409
        expired_objectives = client.get(path, headers=auth).json()
        statuses = {step["id"]: step["status"] for step in expired_objectives["steps"]}
        assert statuses["earn_points"] == "blocked"
        assert statuses["claim_window"] == "complete"
        assert statuses["claim_form"] == "blocked"
        asyncio.run(prepare_points())
        ready = client.get(path, headers=auth).json()
        assert ready["claim_available"] is True
        assert client.get(pending, headers=auth).json() == {
            "season_id": str(season.id),
            "title": season.theme,
        }
        assert client.get(pending, headers=other).json() is None
        assert any(
            step["id"] == "claim_form" and step["status"] == "ready"
            for step in ready["steps"]
        )
        now = end + timedelta(days=3)
        assert client.get(pending, headers=auth).json() is None
        assert not client.get(path, headers=auth).json()["claim_available"]
        now = end + timedelta(minutes=1)

        for _ in range(2):
            claimed = client.post(f"{base}/awakening", headers=auth)
            assert claimed.json()["awakened_character_id"] == "ashblade"
        assert (
            client.get(f"{base}/story", headers=other).json()["awakened_character_id"]
            is None
        )
        owned = client.get(path, headers=auth).json()
        assert owned["awakened_character_id"] == "ashblade"
        assert not owned["claim_available"]
        assert client.get(pending, headers=auth).json() is None
        assert all(step["status"] == "complete" for step in owned["steps"])
    finally:
        asyncio.run(clean())
