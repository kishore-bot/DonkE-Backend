import asyncio
import json
from uuid import UUID, uuid4

import pytest
from donke_engine import OnlineGame
from fastapi.testclient import TestClient
from test_ai import FakeProvider
from test_online import TestGoogle, headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.main import create_app
from app.modules.ai.coaching import MISTAKE_GAP, analyse
from app.modules.ai.insights import card_svg
from app.modules.ai.prompts import PROMPTS, accepted, digest
from app.modules.ai.provider import Written
from app.modules.matches.schemas import EventBatch, GameSeat, MatchReplay
from app.modules.matches.settlement import persist


def played_replay(seed: int, players: list[UUID | None]) -> MatchReplay:
    """Play a real seeded match with engine bots and record it like a server."""
    game = OnlineGame.seeded(len(players), seed)
    opening = game.snapshot()
    batches = []
    while (seat := game.turn) is not None:
        card = game.bot_move(seat, "medium", 0)
        assert card is not None
        events = json.loads(game.play(seat, card))
        batches.append(EventBatch(sequence=len(batches) + 1, events=events))
    finished = next(
        event["outcome"]
        for batch in batches
        for event in batch.events
        if event["event"] == "game_finished"
    )
    return MatchReplay(
        id=uuid4(),
        room_id=uuid4(),
        mode="classic",
        seats=[
            GameSeat(
                player_id=player,
                display_name=f"P{index}" if player else f"Bot {index}",
                ready=True,
                bot=player is None,
            )
            for index, player in enumerate(players)
        ],
        outcome=finished,
        events=batches,
        opening=opening,
    )


def test_prompt_versions_track_their_text():
    for prompt in PROMPTS.values():
        assert digest(prompt.text) == prompt.digest, (
            f"{prompt.id} changed: bump its version and update the digest"
        )


def test_rewording_must_keep_facts_script_and_names():
    fact = "Move 7: you played K♠, but 3♥ was safer (80% vs 40%)."
    good = "Move 7 lesson: K♠ was risky here; 3♥ was the safer card (80% vs 40%)."
    assert accepted(good, fact, "en", 40, ())
    assert not accepted(good.replace("80%", "90%"), fact, "en", 40, ())
    assert not accepted(good.replace("3♥", "4♥"), fact, "en", 40, ())
    assert not accepted("നല്ല കളി " + good, fact, "en", 40, ())
    assert not accepted(good, fact, "en", 5, ())
    assert not accepted(good + " You idiot.", fact, "en", 40, ())
    malayalam = "നീക്കം 7: K♠ അപകടമായിരുന്നു, 3♥ ആയിരുന്നു നല്ലത് (80% / 40%)."
    assert accepted(malayalam, fact, "ml", 40, ())
    assert not accepted(good, fact, "ml", 40, ())
    roast = "അനു is the Donkey with 9 cards!"
    assert accepted(roast, "അനു picked up 9 cards", "en", 20, ("അനു",))
    assert not accepted("Someone has 9 cards", "അനു has 9 cards", "en", 20, ("അനു",))


def test_analysis_scores_real_choices_and_is_reproducible():
    player = uuid4()
    replay = played_replay(3, [player, None, None, None])
    first = analyse(replay, 0, iterations=60)
    assert first == analyse(replay, 0, iterations=60)
    assert first.decisions > 0 and 0.0 <= first.accuracy <= 1.0
    assert sum(item.decisions for item in first.situations.values()) == first.decisions
    gaps = [mistake.gap for mistake in first.mistakes]
    assert all(gap >= MISTAKE_GAP for gap in gaps) and gaps == sorted(
        gaps, reverse=True
    )

    with pytest.raises(AppError) as missing:
        analyse(replay.model_copy(update={"opening": None}), 0)
    assert missing.value.code == "analysis_unavailable"
    other = played_replay(4, [player, None, None, None])
    with pytest.raises(AppError) as mismatch:
        analyse(replay.model_copy(update={"opening": other.opening}), 0, 10)
    assert mismatch.value.code == "analysis_mismatch"


def test_share_card_escapes_names_and_text():
    svg = card_svg("<script>alert(1)</script>", "Tom & Jerry")
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "Tom &amp; Jerry" in svg


class WritingProvider(FakeProvider):
    """Rewords by keeping the fact verbatim behind a friendly opener."""

    def __init__(self):
        super().__init__()
        self.writes: list[str] = []

    async def write(self, task, prompt):
        self.writes.append(task)
        fact = prompt.rsplit(": ", 1)[-1] if task != "tip" else prompt.split("Tip: ")[1]
        return Written(("Nice! " if task != "roast" else "Ha! ") + fact, 20)


@pytest.mark.integration
def test_analysis_tips_insights_and_roast_endpoints(settings):
    provider = WritingProvider()
    with TestClient(
        create_app(settings, TestGoogle(), provider), base_url="https://testserver"
    ) as client:
        tokens = sign_in(client)
        player = UUID(profile(client, tokens)["id"])
        for seed in range(40):
            replay = played_replay(seed, [player, None, None])
            if replay.outcome.get("reason") == "donkey":
                break
        asyncio.run(persist_one(settings, replay))

        path = f"/api/v1/games/{replay.id}/analysis"
        report = client.get(path, headers=headers(tokens))
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["decisions"] > 0
        assert len(body["tips"]) == len(body["mistakes"])
        assert all(tip["source"] == "gemini" for tip in body["tips"])
        assert client.get(path, headers=headers(tokens)).json() == body

        insight = client.get("/api/v1/coach/insights", headers=headers(tokens)).json()
        assert insight["matches"] == 1 and insight["decisions"] == body["decisions"]

        card = client.get(f"/api/v1/games/{replay.id}/roast", headers=headers(tokens))
        assert card.status_code == 200, card.text
        donkey_seat = replay.outcome["seat"]
        name = replay.seats[donkey_seat].display_name
        assert name in card.json()["text"] and card.json()["svg"].startswith("<svg")

        stranger = sign_in(client)
        assert client.get(path, headers=headers(stranger)).status_code == 404


async def persist_one(settings, replay):
    async with open_platform(settings) as platform:
        assert await persist(platform, replay)
