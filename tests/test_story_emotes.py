import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.progression import clock as progression_routes
from app.modules.progression.models import Season
from app.modules.progression.repositories.economy import credit, wallet_lock
from app.modules.progression.schemas import SeasonCreate
from app.modules.progression.services.seasons import create_season
from app.modules.story import dependencies as story_clock
from app.modules.story import highlights

pytestmark = pytest.mark.integration
FAN = "grimoire_fan:emote"


def finish(client, seed, *, call_at=None):
    auth = {"Authorization": "Bearer " + seed["access_token"]}
    path = f"/api/v1/practice/{seed['game_id']}/plays"
    step = seed
    for move in range(60):
        view = step["view"]
        if view["outcome"] is not None:
            break
        response = client.post(
            path,
            headers=auth,
            json={
                "request_id": str(uuid4()),
                "expected_version": view["version"],
                "card": view["legal_moves"][0],
                "call_strike": move == call_at,
            },
        )
        assert response.status_code == 200, response.text
        step = response.json()
    assert step["view"]["outcome"] is not None


def test_owned_season_emote_is_pinned_and_qualifying_strike_is_archived(
    client, settings, monkeypatch
):
    owner, other = sign_in(client), sign_in(client)
    auth, outsider = headers(owner), headers(other)
    player_id = UUID(profile(client, owner)["id"])
    now = datetime(2057, 1, 1, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(progression_routes, "datetime", Clock)
    monkeypatch.setattr(story_clock, "datetime", Clock)

    async def provision():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            season = await create_season(
                db,
                SeasonCreate(
                    theme="Emote fixture",
                    pack_key="grimoire-awakening-v1",
                    starts_at=now,
                    ends_at=now + timedelta(days=21),
                    reason="Season emote tests",
                ),
            )
            wallet = await wallet_lock(db, player_id)
            await credit(db, wallet, f"emote-fixture:{season.id}", "test", 100)
            return season.id

    season_id = asyncio.run(provision())
    loadout = f"/api/v1/seasons/{season_id}/me/emote"

    def begin():
        response = client.post(
            "/api/v1/story/attempts", json={"season_id": str(season_id)}, headers=auth
        )
        assert response.status_code == 201, response.text
        return response.json()

    try:
        assert client.get(loadout).status_code == 401
        starting = client.get(loadout, headers=auth).json()
        assert len(starting["options"]) == 1 and starting["selected"]["sku"] is None
        assert client.put(loadout, json={"sku": FAN}, headers=auth).status_code == 404
        bought = client.post(f"/api/v1/store/{FAN}/buy", headers=auth)
        assert bought.json() == {"coins": 55}
        saved = client.put(loadout, json={"sku": FAN}, headers=auth).json()
        assert saved["selected"] == {
            "sku": FAN,
            "title": "Grimoire Fan",
            "motion": "flourish",
        }
        assert client.get(loadout, headers=auth).json() == saved
        assert (
            client.put(loadout, json={"sku": FAN}, headers=outsider).status_code == 404
        )

        pinned = begin()
        url = f"/api/v1/story/attempts/{pinned['game_id']}/highlight"
        assert pinned["emote"] == saved["selected"]
        assert client.get(url, headers=auth).status_code == 409
        assert client.get(url, headers=outsider).status_code == 404

        cleared = client.put(loadout, json={"sku": None}, headers=auth).json()
        assert cleared["selected"]["sku"] is None
        finish(client, pinned, call_at=11)
        reply = client.get(url, headers=auth)
        assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
        result = reply.json()
        assert result["move"] == 26
        assert result["legal_choices"] >= 2
        assert result["played_safe_rate"] - result["alternative_safe_rate"] >= 0.12
        assert min(result["played_samples"], result["alternative_samples"]) >= 16
        assert result["emote"] == pinned["emote"]
        assert "snapshot" not in reply.text and "seed" not in reply.text

        def cached(*args):
            raise AssertionError("A saved highlight must not be rescored")

        monkeypatch.setattr(highlights, "analyse", cached)
        assert client.get(url, headers=auth).json() == result
        standard = begin()
        assert standard["emote"]["sku"] is None
        finish(client, standard)
        assert (
            client.get(
                f"/api/v1/story/attempts/{standard['game_id']}/highlight", headers=auth
            ).json()
            is None
        )
    finally:

        async def cleanup():
            async with (
                open_platform(settings) as platform,
                platform.sessions.begin() as db,
            ):
                await db.delete(await db.get(Season, season_id))

        asyncio.run(cleanup())
