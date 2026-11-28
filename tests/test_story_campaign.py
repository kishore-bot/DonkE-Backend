import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_multiplayer import prepare_match
from test_online import headers, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.game.models.story_duel import StoryDuel
from app.modules.game.models.story_duel_command import StoryDuelCommand
from app.modules.game.repositories.story import prune_expired
from app.modules.progression.models.season import Season
from app.modules.progression.schemas.seasons import SeasonCreate
from app.modules.progression.services.seasons import create_season
from app.modules.story import dependencies as story_clock

pytestmark = pytest.mark.integration
NOW = datetime(2045, 1, 1, tzinfo=UTC)


def play(client, attempt, capability):
    command = {
        "expected_version": attempt["view"]["version"],
        "request_id": str(uuid4()),
        "card": attempt["view"]["legal_moves"][0],
    }
    response = client.post(
        f"/api/v1/practice/{attempt['game_id']}/plays", json=command, headers=capability
    )
    assert response.status_code == 200, response.text
    return command, {**attempt, **response.json()}


def finish(client, attempt, capability):
    for _ in range(60):
        if attempt["view"]["outcome"] is not None:
            break
        _, attempt = play(client, attempt, capability)
    assert attempt["view"]["outcome"] is not None
    assert 0 in attempt["view"]["escape_order"]
    return attempt


def test_story_campaign_recovers_moves_and_result_across_api_instances(
    settings, monkeypatch
):
    now = NOW

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(story_clock, "datetime", Clock)

    async def provision():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            return await create_season(
                db,
                SeasonCreate(
                    theme="Campaign test",
                    pack_key="grimoire-awakening-v1",
                    starts_at=NOW,
                    ends_at=NOW + timedelta(days=21),
                    reason="Campaign fixture",
                ),
            )

    season = asyncio.run(provision())
    campaign = f"/api/v1/seasons/{season.id}/story/chapters"
    starts = "/api/v1/story/attempts"
    resume = starts + "/resume"

    def start(client, auth, chapter):
        response = client.post(
            starts,
            json={"season_id": str(season.id), "chapter_id": chapter},
            headers=auth,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def settle(client, auth, attempt):
        response = client.post(
            f"{starts}/{attempt['game_id']}/result",
            json={"attempt_token": attempt["access_token"]},
            headers=auth,
        )
        assert response.status_code == 200, response.text
        return response.json()

    def caps(attempt):
        return {"Authorization": "Bearer " + attempt["access_token"]}

    def states(client, auth=None):
        response = client.get(campaign, headers=auth)
        assert response.status_code == 200, response.text
        return [chapter["status"] for chapter in response.json()]

    try:
        with prepare_match(settings) as original:
            auth = headers(sign_in(original))
            other = headers(sign_in(original))
            assert original.get(resume).status_code == 401
            assert states(original, auth) == ["ready", "scheduled", "scheduled"]
            first = start(original, auth, "trial")
            command, moved = play(original, first, caps(first))

        with prepare_match(settings) as reconnected:
            resumed = reconnected.get(resume, headers=auth)
            assert resumed.headers["cache-control"] == "no-store"
            saved = resumed.json()
            assert saved == moved
            assert reconnected.get(resume, headers=other).json() is None
            route = f"/api/v1/practice/{saved['game_id']}"
            assert reconnected.get(route, headers=other).status_code == 404
            same = reconnected.post(route + "/plays", json=command, headers=caps(first))
            assert same.json()["view"] == moved["view"]
            different = {**command, "call_strike": True}
            assert (
                reconnected.post(
                    route + "/plays", json=different, headers=caps(first)
                ).json()["error"]["code"]
                == "request_id_reused"
            )
            finished = finish(reconnected, saved, caps(first))

        with prepare_match(settings) as resumed_result:
            assert (
                resumed_result.get(resume, headers=auth).json()["view"]
                == finished["view"]
            )
            assert settle(resumed_result, auth, finished) == {
                "escaped": True,
                "first_clear": True,
                "coins": 20,
                "points": 40,
            }
            assert resumed_result.get(resume, headers=auth).json() is None

            now = NOW + timedelta(days=7)
            assert states(resumed_result, auth) == ["cleared", "ready", "scheduled"]
            assert states(resumed_result) == ["ready", "sign_in", "scheduled"]
            denied = resumed_result.post(
                starts,
                json={"season_id": str(season.id), "chapter_id": "rival"},
                headers=other,
            )
            assert denied.status_code == 409
            rival = start(resumed_result, auth, "rival")
            assert rival["chapter_title"] == "Grimoire Rivalry"
            won = finish(resumed_result, rival, caps(rival))
            rewards = settle(resumed_result, auth, won)
            assert rewards == {
                "escaped": True,
                "first_clear": True,
                "coins": 20,
                "points": 35,
            }
            assert settle(resumed_result, auth, won) == rewards

            now = NOW + timedelta(days=14)
            assert states(resumed_result, auth) == ["cleared", "cleared", "ready"]
            finale = start(resumed_result, auth, "finale")
            cleared = finish(resumed_result, finale, caps(finale))
            assert settle(resumed_result, auth, cleared)["points"] == 55
            assert states(resumed_result, auth) == ["cleared"] * 3
            assert resumed_result.get("/api/v1/store/wallet", headers=auth).json() == {
                "coins": 70
            }

            async def expire():
                async with (
                    open_platform(settings) as platform,
                    platform.sessions.begin() as db,
                ):
                    row = await db.get(StoryDuel, UUID(first["game_id"]))
                    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    await db.flush()
                    await prune_expired(db, datetime.now(UTC))
                    remaining = await db.scalar(
                        select(func.count())
                        .select_from(StoryDuelCommand)
                        .where(StoryDuelCommand.duel_id == row.id)
                    )
                    assert remaining == 0

            asyncio.run(expire())
            assert resumed_result.get(route, headers=caps(first)).status_code == 404
    finally:

        async def cleanup():
            async with (
                open_platform(settings) as platform,
                platform.sessions.begin() as db,
            ):
                await db.delete(await db.get(Season, season.id))

        asyncio.run(cleanup())
