import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from donke_engine import OnlineGame
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_ai_coaching import WritingProvider, played_replay
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.platform import open_platform
from app.main import create_app
from app.modules.ai.coaching import MatchAnalysis, analyse
from app.modules.ai.fair_play import (
    FairPlayCase,
    Resolve,
    drain,
    resolve,
    review,
    run_analysis,
)
from app.modules.ai.rivals import PlayerRival
from app.modules.matches import bots
from app.modules.matches.schemas import GameSeat
from app.modules.matches.settlement import pending_analysis_key, persist
from scripts.judge_ai import Sample, Verdict, parse_verdict, summarize


def seat(player=None, name="P"):
    return GameSeat(player_id=player, display_name=name, ready=True, bot=player is None)


def test_strength_scales_with_the_table_and_rival_goes_to_the_first_human():
    assert bots.strength(1100) == ("medium", 0)
    assert bots.strength(1600) == ("hard", 200)
    assert bots.strength(9000) == ("hard", 400)
    first, second = uuid4(), uuid4()
    seats = [seat(), seat(first), seat(), seat(second)]
    rival = bots.assign(seats, {first: 2000, second: 2000}, uuid4())
    assert rival == 0 and seats[0].rival_of == first
    assert seats[0].persona == bots.persona_for(first)
    assert seats[0].display_name.endswith("(Rival)")
    assert seats[2].rival_of is None and seats[2].persona is not None
    assert seats[2].level == "hard" and seats[2].iterations == 300
    assert bots.assign([seat(), seat()], {}, uuid4()) is None


def decision_point(seed=2):
    game = OnlineGame.seeded(4, seed)
    while (turn := game.turn) is not None:
        view = json.loads(game.view(turn))
        if len(view["legal_moves"]) >= 3:
            return game, turn
        game.play(turn, game.bot_move(turn, "medium", 0))
    raise AssertionError("no rich decision found")


def test_personas_only_choose_among_near_best_moves():
    game, turn = decision_point()
    scores = json.loads(game.evaluate(turn, 120, 7))
    top = scores[0]["safe_rate"]
    near = [s["card"] for s in scores if s["safe_rate"] >= top - bots.NEAR_BEST]
    for persona in ("thug", "professor", "aunty"):
        bot = GameSeat(
            display_name="B",
            ready=True,
            bot=True,
            level="hard",
            iterations=120,
            persona=persona,
        )
        card = json.loads(bots.choose(game, turn, bot, 7))
        assert card in near
    professor = GameSeat(
        display_name="B",
        ready=True,
        bot=True,
        level="hard",
        iterations=120,
        persona="professor",
    )
    assert json.loads(bots.choose(game, turn, professor, 7)) == scores[0]["card"]
    plain = GameSeat(display_name="B", ready=True, bot=True)
    assert json.loads(bots.choose(game, turn, plain, 1)) in [s["card"] for s in scores]


def test_persona_lines_fire_on_their_own_big_moments():
    bot = GameSeat(display_name="B", ready=True, bot=True, persona="aunty")
    cut = [{"event": "vettu", "cutter": 2, "receiver": 0, "pile": []}]
    assert bots.persona_events(2, bot, cut)[0]["line"] == "cut"
    assert bots.persona_events(0, bot, cut)[0]["line"] == "picked"
    assert bots.persona_events(1, bot, cut) == []
    quiet = GameSeat(display_name="B", ready=True, bot=True)
    assert bots.persona_events(2, quiet, cut) == []


def test_analysis_skips_auto_plays_and_records_think_time():
    replay = played_replay(5, [uuid4(), None, None])
    for batch in replay.events:
        for event in batch.events:
            if event["event"] == "card_played" and event["seat"] == 0:
                event["think_ms"] = 1234
    full = analyse(replay, 0, iterations=30)
    assert full.samples and all(sample.think_ms == 1234 for sample in full.samples)
    assert len(full.samples) == full.decisions
    for batch in replay.events:
        for event in batch.events:
            if event["event"] == "card_played" and event["seat"] == 0:
                event["auto"] = True
    assert analyse(replay, 0, iterations=30).decisions == 0


def test_judge_parses_verdicts_and_groups_by_prompt_version():
    good = parse_verdict('ok {"faithful": true, "helpful": 4, "language_ok": true}')
    assert good == Verdict(faithful=True, helpful=4, language_ok=True)
    assert parse_verdict("no json") is None
    assert (
        parse_verdict('{"faithful": true, "helpful": 9, "language_ok": true}') is None
    )
    sample = Sample("tip@1", "en", "fact", "tip")
    report = summarize([(sample, good), (sample, None)])
    assert report["tip@1"] == {
        "samples": 2,
        "unparseable": 1,
        "faithful_rate": 1.0,
        "helpful_mean": 4.0,
        "language_ok_rate": 1.0,
    }


def test_practice_hint_scores_the_humans_legal_moves():
    with TestClient(create_app()) as client:
        match = client.post("/api/v1/practice", json={"seats": 3, "level": "hard"})
        assert match.status_code == 201, match.text
        body = match.json()
        path = f"/api/v1/practice/{body['game_id']}/hint"
        auth = {"Authorization": f"Bearer {body['access_token']}"}
        hint = client.get(path, headers=auth).json()
        legal = body["view"]["legal_moves"]
        assert [option["card"] for option in hint["options"]] == legal or (
            sorted(json.dumps(o["card"]) for o in hint["options"])
            == sorted(json.dumps(card) for card in legal)
        )
        assert hint["best"] == hint["options"][0]["card"]
        assert client.get(path).status_code == 401
        bad = client.post("/api/v1/practice", json={"level": "godlike"})
        assert bad.status_code == 422


@pytest.mark.integration
def test_rival_record_fair_play_cases_and_background_analysis(settings):
    with TestClient(
        create_app(settings, TestGoogle(), WritingProvider()),
        base_url="https://testserver",
    ) as client:
        tokens = sign_in(client)
        player = UUID(profile(client, tokens)["id"])

        async def scenario():
            async with open_platform(settings) as platform:
                # A ranked match with a rival seat that the player finishes ahead of.
                for seed in range(60):
                    replay = played_replay(seed, [player, None, None])
                    ranks = {
                        e["seat"]: e["place"]
                        for b in replay.events
                        for e in b.events
                        if e["event"] == "player_escaped"
                    }
                    if 0 in ranks and ranks.get(1, 99) > ranks[0]:
                        break
                replay.mode = "ranked"
                replay.seats[1].rival_of = player
                replay.seats[1].persona = bots.persona_for(player)
                assert await persist(platform, replay)
                key = pending_analysis_key(platform)
                assert await platform.redis.zscore(key, str(replay.id)) is not None
                sent: list[str] = []

                async def send(game: str) -> None:
                    sent.append(game)

                assert await drain(platform, send) == 1
                assert sent == [str(replay.id)]
                assert await drain(platform, send) == 0  # leased: not sent twice
                await run_analysis(platform, sent[0])
                assert await platform.redis.zscore(key, str(replay.id)) is None
                async with platform.sessions() as db:
                    rival = await db.get(PlayerRival, player)
                    assert rival is not None and (rival.games, rival.wins) == (1, 1)
                    analysed = await db.scalar(
                        select(func.count()).where(MatchAnalysis.player_id == player)
                    )
                    assert analysed == 1

                # Engine-perfect, instant play over many decisions opens one case.
                fast = {"think_ms": 300, "legal": 4, "top": True}
                async with platform.sessions.begin() as db:
                    db.add(
                        MatchAnalysis(
                            game_id=replay.id,
                            player_id=(
                                suspect := UUID(profile(client, sign_in(client))["id"])
                            ),
                            decisions=200,
                            accuracy=1.0,
                            payload={
                                "decisions": 200,
                                "accuracy": 1.0,
                                "mistakes": [],
                                "situations": {},
                                "samples": [fast] * 200,
                            },
                        )
                    )
                async with platform.sessions.begin() as db:
                    case = await review(db, suspect, datetime.now(UTC))
                    assert case is not None and case.score == 65
                async with platform.sessions.begin() as db:
                    again = await review(db, suspect, datetime.now(UTC))
                    assert again is not None and again.id == case.id
                async with platform.sessions.begin() as db:
                    closed = await resolve(
                        db, case.id, Resolve(decision="dismissed", reason="Pro player")
                    )
                    assert closed.status == "dismissed" and closed.note == "Pro player"
                async with platform.sessions() as db:
                    open_cases = await db.scalar(
                        select(func.count()).where(
                            FairPlayCase.player_id == suspect,
                            FairPlayCase.status == "open",
                        )
                    )
                    assert open_cases == 0

        asyncio.run(scenario())
        mine = client.get("/api/v1/rival", headers=headers(tokens)).json()
        assert (mine["games"], mine["wins"]) == (1, 1)
        assert mine["name"] in mine["taunt"]
        lines = client.get("/api/v1/personas/lines", headers=headers(tokens)).json()
        assert set(lines["personas"]) == {"thug", "professor", "aunty"}


def test_taskiq_jobs_are_registered_with_retries_and_schedules():
    from app.workers import jobs

    analyse = jobs.broker.find_task("donke.analyse_match")
    drain_task = jobs.broker.find_task("donke.drain_analysis")
    prune = jobs.broker.find_task("donke.prune_sessions")
    assert analyse is not None and analyse.labels["retry_on_error"] is True
    assert drain_task is not None and drain_task.labels["schedule"] == [
        {"cron": "* * * * *"}
    ]
    assert prune is not None and prune.labels["schedule"][0]["cron"] == "17 * * * *"
