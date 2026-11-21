import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.modules.matches.schemas import EventBatch, GameSeat, MatchReplay
from app.modules.matches.settlement import persist
from app.modules.progression.models import (
    PlayerSkill,
    PlayerStats,
    Season,
    SeasonDay,
    SeasonPlayer,
    Wallet,
)
from app.modules.progression.service import streak_stars

pytestmark = pytest.mark.integration


def duel(winner: UUID, donkey: UUID) -> MatchReplay:
    return MatchReplay(
        id=uuid4(),
        room_id=uuid4(),
        mode="classic",
        seats=[
            GameSeat(player_id=winner, display_name="Winner", ready=True, bot=False),
            GameSeat(player_id=donkey, display_name="Donkey", ready=True, bot=False),
        ],
        outcome={"reason": "donkey", "seat": 1},
        events=[
            EventBatch(
                sequence=1,
                events=[
                    {"event": "card_played", "seat": 0, "card": {}},
                    {
                        "event": "vettu",
                        "cutter": 0,
                        "receiver": 1,
                        "pile": [{"seat": 1}, {"seat": 0}],
                    },
                    {"event": "player_escaped", "seat": 0, "place": 1},
                ],
            )
        ],
    )


def test_matches_build_stats_achievements_skill_and_streak_stars(client, settings):
    tokens = [sign_in(client), sign_in(client)]
    winner, donkey = (UUID(profile(client, token)["id"]) for token in tokens)
    monday = datetime(2021, 3, 1, 12, tzinfo=UTC)
    last: list[MatchReplay] = []

    async def play_week():
        async with open_platform(settings) as platform:
            async with platform.sessions.begin() as db:
                season = Season(
                    theme="Streak Test",
                    starts_at=monday,
                    ends_at=monday + timedelta(days=28),
                )
                db.add(season)
            for day in range(5):
                match = duel(winner, donkey)
                last.append(match)
                finished = monday + timedelta(days=day)
                assert await persist(platform, match, finished_at=finished)
            async with platform.sessions() as db:
                won = await db.get(PlayerStats, winner)
                lost = await db.get(PlayerStats, donkey)
                assert won is not None and lost is not None
                assert (won.games, won.escapes, won.firsts, won.cuts_given) == (
                    5,
                    5,
                    5,
                    5,
                )
                assert won.best_safe_streak == 5 and won.safe_streak == 5
                assert (lost.donkeys, lost.safe_streak, lost.cards_picked) == (5, 0, 10)
                wallet = await db.get(Wallet, winner)
                # 5 x 15 match coins + First Escape (20) + First Crown (25).
                assert wallet is not None and wallet.coins == 120
                progress = await db.get(SeasonPlayer, (season.id, winner))
                assert progress is not None and progress.points == 5 * 10
                assert await streak_stars(db, season.id, winner) == 1
                skills = {
                    player: await db.get(PlayerSkill, player)
                    for player in (winner, donkey)
                }
                assert skills[winner] is not None and skills[donkey] is not None
                assert skills[winner].mu > 25 > skills[donkey].mu
                assert skills[winner].matches == 5

    asyncio.run(play_week())

    mine = client.get("/api/v1/achievements", headers=headers(tokens[0])).json()
    unlocked = {item["key"] for item in mine["achievements"] if item["unlocked_at"]}
    assert unlocked == {"first_escape", "first_crown"}
    assert mine["stats"]["games"] == 5

    path = f"/api/v1/games/{last[-1].id}/analytics"
    report = client.get(path, headers=headers(tokens[1])).json()
    assert report["total_vettus"] == 1
    assert report["seats"][1]["donkey"] and report["seats"][1]["cards_picked"] == 2
    assert report["seats"][0]["badges"] == ["vettu_king"]
    stranger = sign_in(client)
    assert client.get(path, headers=headers(stranger)).status_code == 404


def test_streak_bonus_track_claims_once_and_stays_locked_without_stars(
    client, settings
):
    tokens = sign_in(client)
    player = UUID(profile(client, tokens)["id"])
    now = datetime.now(UTC)
    week = now.date() - timedelta(days=now.weekday())

    async def open_season() -> UUID:
        async with (
            open_platform(settings) as platform,
            platform.sessions.begin() as db,
        ):
            season = Season(
                theme="Bonus Test",
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(days=28),
            )
            db.add(season)
            await db.flush()
            db.add(SeasonPlayer(season_id=season.id, player_id=player, points=0))
            db.add_all(
                SeasonDay(
                    season_id=season.id,
                    player_id=player,
                    day=week + timedelta(days=offset),
                )
                for offset in range(5)
            )
            return season.id

    async def close_season(season_id: UUID) -> None:
        async with (
            open_platform(settings) as platform,
            platform.sessions.begin() as db,
        ):
            season = await db.get(Season, season_id)
            if season is not None:
                await db.delete(season)

    season_id = asyncio.run(open_season())
    try:
        current = client.get("/api/v1/seasons/current", headers=headers(tokens)).json()
        assert current["season"]["id"] == str(season_id)
        assert (current["stars"], current["streak_days"]) == (1, 5)
        assert [perk["active"] for perk in current["perks"]] == [False, False, False]
        claim = f"/api/v1/seasons/{season_id}/bonus/1/claim"
        assert client.post(claim, headers=headers(tokens)).json() == {"credited": True}
        assert client.post(claim, headers=headers(tokens)).json() == {"credited": False}
        locked = client.post(
            f"/api/v1/seasons/{season_id}/bonus/2/claim", headers=headers(tokens)
        )
        assert locked.status_code == 409
        assert locked.json()["error"]["code"] == "bonus_locked"
        inventory = client.get("/api/v1/store/inventory", headers=headers(tokens))
        assert f"bonus:{season_id}:1:emote" in inventory.json()
    finally:
        asyncio.run(close_season(season_id))


def test_festival_items_cannot_be_bought_out_of_season(client):
    tokens = sign_in(client)
    catalog = client.get("/api/v1/store/catalog", headers=headers(tokens)).json()
    items = {item["sku"]: item for item in catalog}
    assert items["monsoon_back"]["available"] is True
    closed = [sku for sku, item in items.items() if not item["available"]]
    assert closed, "at least one festival is always out of season"
    response = client.post(f"/api/v1/store/{closed[0]}/buy", headers=headers(tokens))
    assert response.status_code == 409
    assert response.json()["error"]["code"] in {
        "cosmetic_unavailable",
        "insufficient_coins",
    }
