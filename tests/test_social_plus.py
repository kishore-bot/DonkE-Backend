import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_admin_console import admin_login
from test_ai_coaching import played_replay
from test_multiplayer import prepare_match, ready_room
from test_online import client as client  # noqa: PLC0414
from test_online import headers, profile, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.main import create_app
from app.modules.matches.service import MatchService
from app.modules.matches.settlement import persist
from app.modules.social.safety import clean


def test_chat_text_is_cleaned_masked_and_bounded():
    assert clean("  you   IDIOT ") == "you *****"
    assert clean("class act") == "class act"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(AppError) as error:
            clean(bad)
        assert error.value.code == "invalid_message"


def test_join_landing_page_links_into_the_app():
    with TestClient(create_app()) as plain:
        page = plain.get("/join/Ab3_-x9Z")
        assert page.status_code == 200 and 'href="donke://join/Ab3_-x9Z"' in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert plain.get("/join/<script>").status_code in {404, 422}


def befriend(client, first, second):
    other = profile(client, second)["id"]
    me = profile(client, first)["id"]
    assert (
        client.post(f"/api/v1/friends/{other}", headers=headers(first)).status_code
        == 204
    )
    assert (
        client.put(f"/api/v1/friends/{me}", headers=headers(second)).status_code == 204
    )
    return me, other


@pytest.mark.integration
def test_blocks_presence_chat_mutes_reports_and_head_to_head(client, settings):
    alice, bob, cara = (sign_in(client) for _ in range(3))
    a_id, b_id = befriend(client, alice, bob)
    _, c_id = befriend(client, alice, cara)

    # Presence: any authenticated call marks a friend online.
    client.get("/api/v1/auth/me", headers=headers(cara))
    friends = {
        f["player"]["id"]: f
        for f in client.get("/api/v1/friends", headers=headers(alice)).json()
    }
    assert friends[c_id]["online"] is True and friends[c_id]["activity"] == "idle"

    # Chat with the word filter, oldest first, polled with `after`.
    posted = client.post(
        "/api/v1/chat/global", json={"text": "gg you idiot"}, headers=headers(bob)
    )
    assert posted.status_code == 201 and posted.json()["text"] == "gg you *****"
    client.post("/api/v1/chat/global", json={"text": "hello"}, headers=headers(cara))
    seen = client.get("/api/v1/chat/global", headers=headers(alice)).json()
    assert [m["text"] for m in seen[-2:]] == ["gg you *****", "hello"]
    newer = client.get(
        "/api/v1/chat/global", params={"after": seen[-2]["id"]}, headers=headers(alice)
    ).json()
    assert [m["text"] for m in newer] == ["hello"]

    # Blocking ends the friendship, hides chat and stops requests.
    assert (
        client.post(f"/api/v1/blocks/{b_id}", headers=headers(alice)).status_code == 204
    )
    ids = [
        f["player"]["id"]
        for f in client.get("/api/v1/friends", headers=headers(alice)).json()
    ]
    assert b_id not in ids
    hidden = client.get("/api/v1/chat/global", headers=headers(alice)).json()
    assert all(m["player_id"] != b_id for m in hidden)
    again = client.post(f"/api/v1/friends/{a_id}", headers=headers(bob))
    assert (
        again.status_code == 403 and again.json()["error"]["code"] == "player_blocked"
    )
    assert client.get("/api/v1/blocks", headers=headers(alice)).json() == [b_id]
    client.delete(f"/api/v1/blocks/{b_id}", headers=headers(alice))
    assert (
        client.post(f"/api/v1/friends/{a_id}", headers=headers(bob)).status_code == 204
    )

    # Reports: one open report per pair a day; moderators resolve them.
    body = {"player_id": b_id, "reason": "abuse", "note": "Rude in chat"}
    first = client.post("/api/v1/reports", json=body, headers=headers(alice)).json()
    assert (
        client.post("/api/v1/reports", json=body, headers=headers(alice)).json()["id"]
        == first["id"]
    )
    _, csrf = admin_login(client, settings)
    listed = client.get("/api/v1/admin/reports").json()
    assert first["id"] in [r["id"] for r in listed]
    resolved = client.post(
        f"/api/v1/admin/reports/{first['id']}/resolve",
        json={"decision": "actioned", "reason": "Muted for a day"},
        headers=csrf,
    )
    assert resolved.json()["status"] == "actioned"

    # A chat mute stops chat but not play; minutes 0 lifts it.
    muted = client.post(
        f"/api/v1/admin/players/{b_id}/mute",
        json={"minutes": 60, "reason": "Abuse"},
        headers=csrf,
    )
    assert muted.json()["muted_until"] is not None
    blocked = client.post(
        "/api/v1/chat/global", json={"text": "hi"}, headers=headers(bob)
    )
    assert (
        blocked.status_code == 403 and blocked.json()["error"]["code"] == "chat_muted"
    )
    client.post(
        f"/api/v1/admin/players/{b_id}/mute",
        json={"minutes": 0, "reason": "Lifted"},
        headers=csrf,
    )
    assert (
        client.post(
            "/api/v1/chat/global", json={"text": "sorry"}, headers=headers(bob)
        ).status_code
        == 201
    )

    # Head-to-head from shared match replays.
    async def shared_match():
        async with open_platform(settings) as platform:
            replay = played_replay(8, [UUID(a_id), UUID(c_id), None])
            assert await persist(platform, replay)
            return replay

    replay = asyncio.run(shared_match())
    record = client.get(
        f"/api/v1/friends/{c_id}/together", headers=headers(alice)
    ).json()
    assert (
        record["games"] == 1
        and record["ahead"] + record["behind"] + record["tied"] == 1
    )
    mirrored = client.get(
        f"/api/v1/friends/{a_id}/together", headers=headers(cara)
    ).json()
    assert (mirrored["ahead"], mirrored["behind"]) == (
        record["behind"],
        record["ahead"],
    )
    donkey = replay.outcome.get("seat")
    assert record["my_donkeys"] == int(donkey == 0)


@pytest.mark.integration
def test_room_invites_links_and_in_match_emotes(settings):
    config = settings.model_copy(update={"room_start_seconds": 0})
    with prepare_match(config) as client:
        host, friend, stranger = (sign_in(client) for _ in range(3))
        befriend(client, host, friend)
        room = client.post(
            "/api/v1/rooms", json={"capacity": 3}, headers=headers(host)
        ).json()
        friend_id = profile(client, friend)["id"]

        invited = client.post(
            f"/api/v1/rooms/{room['id']}/invites/{friend_id}", headers=headers(host)
        )
        assert invited.status_code == 204
        inbox = client.get("/api/v1/invites/rooms", headers=headers(friend)).json()
        assert [i["room_id"] for i in inbox] == [room["id"]]
        stranger_id = profile(client, stranger)["id"]
        assert (
            client.post(
                f"/api/v1/rooms/{room['id']}/invites/{stranger_id}",
                headers=headers(host),
            ).status_code
            == 403
        )

        link = client.post(
            f"/api/v1/rooms/{room['id']}/link", headers=headers(host)
        ).json()
        assert link["app_link"] == f"donke://join/{link['code']}"
        # No public_base_url configured: the link uses the request's origin.
        assert link["url"] == f"http://testserver/join/{link['code']}"
        joined = client.post(
            f"/api/v1/invites/{link['code']}/join", headers=headers(stranger)
        )
        assert joined.status_code == 200, joined.text
        assert stranger_id in [s["player_id"] for s in joined.json()["seats"]]
        assert (
            client.post(
                "/api/v1/invites/zzzzzzzz/join", headers=headers(friend)
            ).status_code
            == 404
        )

        players = [headers(sign_in(client)) for _ in range(2)]
        _, room_id = ready_room(client, players)

        async def start():
            async with open_platform(config) as platform:
                return await MatchService(platform).start(room_id)

        game = asyncio.run(start())
        path = f"/api/v1/games/{game}/ws"
        with client.websocket_connect(path, headers=players[0]) as socket:
            socket.receive_json()  # opening events
            socket.receive_json()  # state_sync
            socket.send_json({"action": "emote", "emote": "namaste"})
            feed = socket.receive_json()
            while feed["type"] != "feed":
                feed = socket.receive_json()
            assert (feed["kind"], feed["value"]) == ("emote", "namaste")
            socket.send_json({"action": "emote", "emote": "not_owned:emote"})
            error = socket.receive_json()
            while error["type"] != "error":
                error = socket.receive_json()
            assert error["code"] == "invalid_emote"
            socket.send_json({"action": "chat", "text": "nice cut, idiot"})
            chat = socket.receive_json()
            while chat["type"] != "feed":
                chat = socket.receive_json()
            assert chat["value"] == "nice cut, *****"


@pytest.mark.parametrize(
    ("text", "blocked"),
    [
        ("പോടാ മൈരേ", True),
        ("നീ തെണ്ടി ആണ്", True),
        ("thayolikal", True),
        ("நீ தேவடியா பையன்", True),
        ("साला चूतिया है", True),
        ("bsdk", True),
        ("ಸೂಳೆಮಗ", True),
        ("లంజకొడుకు", True),
        ("Fucking hell", True),
        ("5h1t", True),
        ("first class poori and chettan", False),
        ("a laudable fire retardant", False),
        ("గుద్దు ఇచ్చాడు", False),
        ("Kunnamkulam", False),
        ("Scunthorpe", False),
        ("randu kali", False),
    ],
)
def test_word_list_covers_every_language_without_common_false_positives(text, blocked):
    assert (clean(text) != text) is blocked
