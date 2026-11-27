import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414
from test_social_plus import befriend

from app.core.platform import open_platform
from app.modules.progression import clock as season_routes
from app.modules.progression.models import Season, SeasonDay, SeasonPlayer, WeeklyPlayer
from app.modules.progression.schemas import SeasonCreate
from app.modules.progression.services import season_rewards
from app.modules.progression.services.seasons import create_season
from app.modules.story import dependencies as story_clock

pytestmark = pytest.mark.integration
START = datetime(2042, 6, 1, tzinfo=UTC)
END = START + timedelta(days=21)


def create_pack(settings):
    async def create():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            return await create_season(
                db,
                SeasonCreate(
                    theme="Finale test",
                    pack_key="grimoire-awakening-v1",
                    starts_at=START,
                    ends_at=END,
                    reason="Fixture",
                ),
            )

    return asyncio.run(create())


def cleanup(settings, season_id):
    async def delete():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            await db.delete(await db.get(Season, season_id))

    asyncio.run(delete())


def test_gifts_from_prior_acts_remain_claimable_during_packed_season_grace(
    client, settings, monkeypatch
):
    now = START + timedelta(days=15)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(season_rewards, "datetime", Clock)
    season = create_pack(settings)
    tokens = sign_in(client)
    auth, other = headers(tokens), headers(sign_in(client))
    player = UUID(profile(client, tokens)["id"])
    first, third = START.date(), (START + timedelta(days=14)).date()
    path = f"/api/v1/seasons/{season.id}"
    inbox = "/api/v1/seasons/rewards"

    async def prepare():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            db.add(SeasonPlayer(season_id=season.id, player_id=player, points=90))
            db.add_all(
                WeeklyPlayer(season_id=season.id, player_id=player, week=week, games=3)
                for week in (first, third)
            )
            db.add_all(
                SeasonDay(
                    season_id=season.id,
                    player_id=player,
                    day=first + timedelta(days=day),
                )
                for day in range(5)
            )

    try:
        asyncio.run(prepare())
        assert client.get(inbox).status_code == 401
        assert client.get(inbox, headers=other).json() == []
        response = client.get(inbox, headers=auth)
        assert response.headers["cache-control"] == "no-store"
        earned = response.json()[0]["gifts"]
        assert [gift["act"] for gift in earned if gift["kind"] == "weekly"] == [1, 3]
        weekly = path + "/weekly/play_three/claim"
        assert (
            client.post(
                weekly, params={"week": first + timedelta(days=1)}, headers=auth
            ).json()["error"]["code"]
            == "reward_week_unavailable"
        )
        assert client.post(weekly, params={"week": first}, headers=auth).json() == {
            "credited": True
        }
        now = END + timedelta(days=1)
        assert client.post(weekly, params={"week": first}, headers=auth).json() == {
            "credited": False
        }
        assert client.post(weekly, headers=auth).json() == {"credited": True}
        assert client.post(path + "/tiers/10/claim", headers=auth).json() == {
            "credited": True
        }
        bonus = path + "/bonus/1/claim"
        assert client.post(bonus, headers=auth).json() == {"credited": True}
        assert client.post(bonus, headers=auth).json() == {"credited": False}
        assert client.get("/api/v1/store/wallet", headers=auth).json() == {"coins": 15}
        claim_rows = client.get(inbox, headers=auth).json()[0]["gifts"]
        assert all(row["claimed"] for row in claim_rows if row["act"] in (1, 3))
        assert next(row for row in claim_rows if row["kind"] == "bonus")["claimed"]
        now = END + timedelta(days=3)
        assert client.get(inbox, headers=auth).json() == []
        assert client.post(path + "/tiers/11/claim", headers=auth).status_code == 409
    finally:
        cleanup(settings, season.id)


def play_escape(client, attempt, auth):
    identifier = attempt["game_id"]
    access = attempt["access_token"]
    path = f"/api/v1/practice/{identifier}/plays"
    own_game = {"Authorization": "Bearer " + access}
    for _ in range(50):
        view = attempt["view"]
        if view["outcome"]:
            break
        played = client.post(
            path,
            json={
                "request_id": str(uuid4()),
                "expected_version": view["version"],
                "card": view["legal_moves"][0],
            },
            headers=own_game,
        )
        assert played.status_code == 200, played.text
        attempt = played.json()
    assert 0 in attempt["view"]["escape_order"]
    receipt_path = f"/api/v1/story/attempts/{identifier}/result"
    for _ in range(2):
        response = client.post(
            receipt_path, json={"attempt_token": access}, headers=auth
        )
        assert response.status_code == 200, response.text
    return response.json()


def test_squad_roster_is_frozen_and_story_clear_and_gift_are_idempotent(
    client, settings, monkeypatch
):
    now = END - timedelta(days=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(story_clock, "datetime", Clock)
    monkeypatch.setattr(season_routes, "datetime", Clock)
    season = create_pack(settings)
    alice, bob, cara = (sign_in(client) for _ in range(3))
    _, bob_id = befriend(client, alice, bob)
    _, cara_id = befriend(client, alice, cara)
    leader, teammate, outsider = (headers(tokens) for tokens in (alice, bob, cara))
    path = f"/api/v1/seasons/{season.id}/squad"
    overview = "/api/v1/seasons/squads"

    def start(auth):
        response = client.post(
            "/api/v1/story/attempts", json={"season_id": str(season.id)}, headers=auth
        )
        assert response.status_code == 201, response.text
        return response.json()

    def join(party, player, auth):
        invited = client.post(f"/api/v1/parties/invite/{player}", headers=leader)
        assert invited.status_code == 204
        assert (
            client.post(f"/api/v1/parties/{party}/join", headers=auth).status_code
            == 200
        )

    try:
        party = client.post("/api/v1/parties", headers=leader).json()["id"]
        join(party, bob_id, teammate)
        old_attempt = start(leader)
        assert client.post(path, headers=teammate).status_code == 403
        enrolled = client.post(path, headers=leader).json()
        assert enrolled["target"] == 2 and enrolled["completed"] == 0
        assert client.post(path, headers=leader).json() == enrolled
        assert play_escape(client, old_attempt, leader)["first_clear"]
        assert (
            client.get(overview, headers=leader).json()["squads"][0]["completed"] == 0
        )

        assert client.post("/api/v1/parties/leave", headers=teammate).status_code == 204
        join(party, cara_id, outsider)
        assert client.get(overview, headers=outsider).json()["squads"] == []
        assert client.post(path + "/claim", headers=outsider).status_code == 404
        assert client.post(path + "/claim", headers=teammate).status_code == 409

        assert not play_escape(client, start(leader), leader)["first_clear"]
        assert (
            client.get(overview, headers=teammate).json()["squads"][0]["completed"] == 1
        )
        final_attempt = start(teammate)
        now = END + timedelta(days=1)
        assert play_escape(client, final_attempt, teammate)["first_clear"]
        ready = client.get(overview, headers=leader).json()
        assert ready["active_season_id"] is None
        assert ready["squads"][0]["can_claim"]
        assert ready["squads"][0]["completed"] == 2
        claimed = client.post(path + "/claim", headers=leader).json()
        assert claimed["claimed"] and not claimed["can_claim"]
        assert client.post(path + "/claim", headers=leader).json() == claimed
        assert client.get("/api/v1/store/wallet", headers=leader).json() == {
            "coins": 80
        }
        frame = f"squad:{season.id}:frame"
        assert (
            client.put(f"/api/v1/store/{frame}/equip", headers=leader).status_code
            == 204
        )
        catalog = client.get("/api/v1/store/catalog", headers=leader).json()
        earned = next(item for item in catalog if item["sku"] == frame)
        assert earned["owned"] and earned["equipped"]
        now = END + timedelta(days=3)
        assert client.get(overview, headers=teammate).json()["squads"] == []
        assert client.post(path + "/claim", headers=teammate).status_code == 409
        assert client.post(path + "/claim", headers=leader).json() == claimed
    finally:
        cleanup(settings, season.id)
