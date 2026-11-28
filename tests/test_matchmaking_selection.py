import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.lobby.helpers.selection import choose
from app.modules.lobby.repositories.lobby import LobbyRepository
from app.modules.lobby.services.lobby import LobbyService
from app.workers.matchmaking import DatabaseFacts, match_once


def entry(player, waited_ms, party=None):
    return {"player_id": str(player), "since": 100_000 - waited_ms, "party": party}


def test_tables_follow_hidden_skill_and_wait_for_humans_before_bots():
    strong = [uuid4() for _ in range(4)]
    weak = [uuid4() for _ in range(4)]
    skills = {**dict.fromkeys(strong, 40.0), **dict.fromkeys(weak, 15.0)}
    queue = [entry(p, 5_000 - i) for i, p in enumerate(strong + weak)]
    table = choose(queue, 100_000, skills, [], 4, bot_wait_seconds=10)
    assert table is not None and set(table) == {str(p) for p in strong}
    # Three humans and no long wait: keep waiting rather than add a bot.
    early = [entry(p, 2_000) for p in strong[:3]]
    assert choose(early, 100_000, skills, [], 4, bot_wait_seconds=10) is None
    late = [entry(p, 12_000) for p in strong[:3]]
    assert choose(late, 100_000, skills, [], 4, bot_wait_seconds=10) is not None


def test_players_who_blocked_each_other_never_share_a_table():
    players = [uuid4() for _ in range(5)]
    queue = [entry(p, 9_000 - i) for i, p in enumerate(players)]
    avoid = [(str(players[0]), str(players[1]))]
    table = choose(queue, 100_000, {}, avoid, 4, bot_wait_seconds=60)
    assert table is not None and str(players[0]) in table
    assert str(players[1]) not in table and len(table) == 4


@pytest.mark.integration
def test_worker_claims_exactly_the_selected_table(settings):
    config = settings.model_copy(update={"bot_fill_seconds": 60})
    with TestClient(
        create_app(config, TestGoogle()), base_url="https://testserver"
    ) as client:
        tokens = [sign_in(client) for _ in range(5)]
        ids = [profile(client, token)["id"] for token in tokens]
        # The first two in queue order have blocked each other.
        assert (
            client.post(
                f"/api/v1/blocks/{ids[1]}", headers=headers(tokens[0])
            ).status_code
            == 204
        )
        for token in tokens:
            joined = client.post(
                "/api/v1/matchmaking/join", headers=headers(token), json={}
            )
            assert joined.status_code == 200, joined.text

        async def run():
            async with open_platform(config) as platform:
                lobby = LobbyService(
                    LobbyRepository(platform.redis, config), DatabaseFacts(platform)
                )
                return await match_once(lobby)

        assert asyncio.run(run()) == 1
        status = {
            pid: client.get("/api/v1/matchmaking/status", headers=headers(t)).json()[
                "status"
            ]
            for pid, t in zip(ids, tokens, strict=True)
        }
        seated = {pid for pid, state in status.items() if state != "queued"}
        assert len(seated) == 4 and ids[0] in seated and ids[1] not in seated
        assert UUID(ids[1]) and status[ids[1]] == "queued"
