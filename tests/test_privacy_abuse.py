import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_ai_coaching import played_replay
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.config import Settings
from app.core.platform import open_platform
from app.core.rate_limit import client_host
from app.main import create_app
from app.modules.matches.models import MatchPlayer
from app.modules.matches.schemas import GameSeat, PublicReplay
from app.modules.matches.settlement import persist, rated_changes


def test_public_replay_never_carries_the_opening_deal():
    replay = played_replay(2, [uuid4(), None])
    assert replay.opening is not None
    public = PublicReplay.of(replay)
    assert "opening" not in public.model_dump()
    assert "opening" not in PublicReplay.model_json_schema()["properties"]
    assert public.events == replay.events


def test_ranked_ratings_need_two_humans_at_the_table():
    human, rival = uuid4(), uuid4()
    solo = played_replay(1, [human, None, None])
    solo.mode = "ranked"
    assert rated_changes(solo) == {}  # bots cannot be farmed for MMR
    duo = played_replay(1, [human, rival, None])
    duo.mode = "ranked"
    if duo.outcome.get("reason") == "donkey":
        assert rated_changes(duo)
    forfeited = duo.model_copy(deep=True)
    forfeited.seats[1] = GameSeat(
        player_id=rival, display_name="R", ready=True, bot=True, forfeited=True
    )
    assert rated_changes(forfeited)[rival] < 0  # a leaver still counts and pays


def practice_client(**overrides):
    base = {"practice_sessions_per_client": 2, "practice_creates_per_minute": 3}
    return TestClient(create_app(Settings(_env_file=None, **(base | overrides))))


def test_practice_caps_each_client_without_locking_out_others():
    with practice_client() as client:
        for _ in range(2):
            assert client.post("/api/v1/practice", json={}).status_code == 201
        capped = client.post("/api/v1/practice", json={})
        assert capped.status_code == 429
        assert capped.json()["error"]["code"] == "practice_limit"
        service = client.app.state.practice
        other = service.create(4, "easy", "203.0.113.9")
        assert other.game_id  # another client is unaffected


def test_practice_creation_is_rate_limited_per_client():
    with practice_client(practice_sessions_per_client=50) as client:
        codes = [client.post("/api/v1/practice", json={}).status_code for _ in range(4)]
        assert codes == [201, 201, 201, 429]


def request_from(peer: str, forwarded: str | None, trusted: tuple) -> SimpleNamespace:
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={"x-forwarded-for": forwarded} if forwarded else {},
        app=SimpleNamespace(state=SimpleNamespace(trusted_proxies=trusted)),
    )


def test_client_ip_trusts_forwarded_for_only_from_proxies():
    from ipaddress import ip_network

    proxies = (ip_network("10.0.0.0/8"), ip_network("127.0.0.0/8"))
    # Through a proxy: the real client is the last hop that is not a proxy.
    assert (
        client_host(request_from("10.0.0.2", "198.51.100.7, 10.0.0.9", proxies))
        == "198.51.100.7"
    )
    # A client spoofing the header directly is ignored.
    assert (
        client_host(request_from("198.51.100.7", "1.2.3.4", proxies)) == "198.51.100.7"
    )
    assert client_host(request_from("10.0.0.2", "garbage", proxies)) == "garbage"
    assert client_host(request_from("10.0.0.2", None, proxies)) == "10.0.0.2"


@pytest.mark.integration
def test_replay_endpoint_hides_hands_and_player_index_is_written(settings):
    with TestClient(
        create_app(settings, TestGoogle()), base_url="https://testserver"
    ) as client:
        tokens = sign_in(client)
        player = UUID(profile(client, tokens)["id"])
        replay = played_replay(6, [player, None, None])

        async def settle():
            async with open_platform(settings) as platform:
                assert await persist(platform, replay)
                assert not await persist(platform, replay)  # retry is a no-op
                async with platform.sessions() as db:
                    return list(
                        await db.scalars(
                            select(MatchPlayer).where(MatchPlayer.game_id == replay.id)
                        )
                    )

        rows = asyncio.run(settle())
        assert [(row.player_id, row.seat) for row in rows] == [(player, 0)]
        body = client.get(
            f"/api/v1/games/{replay.id}/replay", headers=headers(tokens)
        ).json()
        assert "opening" not in body and body["events"]
        assert "Spades" not in str(body.get("seats"))


@pytest.mark.integration
def test_settlement_retry_queues_analysis_a_failed_attempt_missed(
    settings, monkeypatch
):
    from redis.exceptions import RedisError

    from app.modules.matches.settlement import pending_analysis_key

    async def scenario():
        async with open_platform(settings) as platform:
            async with platform.sessions.begin() as db:
                from app.modules.identity.models import Player

                players = [Player(google_sub=uuid4().hex, display_name=n) for n in "AB"]
                db.add_all(players)
                await db.flush()
                ids = [p.id for p in players]
            replay = played_replay(4, [ids[0], ids[1], None])
            replay.mode = "ranked"
            real = platform.redis.zadd

            async def lost(*args, **kwargs):
                raise RedisError("timeout after commit")

            monkeypatch.setattr(platform.redis, "zadd", lost)
            with pytest.raises(RedisError):
                await persist(platform, replay)  # committed, but not queued
            monkeypatch.setattr(platform.redis, "zadd", real)
            assert await persist(platform, replay) is False  # already stored ...
            queued = await platform.redis.zscore(
                pending_analysis_key(platform), str(replay.id)
            )
            assert queued is not None  # ... yet the retry queued the analysis

    asyncio.run(scenario())
