import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.progression import router as season_routes
from app.modules.progression.models import Season, SeasonDay, SeasonPlayer
from app.modules.progression.schemas import SeasonCreate
from app.modules.progression.service import create_season, streak_stars, week_start
from app.modules.story import router as story_routes


@pytest.mark.integration
def test_seeded_story_call_first_clear_and_final_form(client, settings, monkeypatch):
    start = datetime(2038, 7, 1, tzinfo=UTC)
    end = start + timedelta(days=21)
    now = start + timedelta(days=20)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(story_routes, "datetime", Clock)
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
        now = end + timedelta(minutes=1)
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
        assert client.post(f"{base}/awakening", headers=auth).status_code == 409
        asyncio.run(prepare_points())
        for _ in range(2):
            claimed = client.post(f"{base}/awakening", headers=auth)
            assert claimed.json()["awakened_character_id"] == "ashblade"
        assert (
            client.get(f"{base}/story", headers=other).json()["awakened_character_id"]
            is None
        )
    finally:
        asyncio.run(clean())
