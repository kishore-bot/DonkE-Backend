from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

pytest.importorskip("a2a", exc_type=ModuleNotFoundError)

from app.services.localization_review import ReviewSettings, create_app

AUTH = {
    "A2A-Version": "1.0",
    "Authorization": "Bearer test-localization-01234567890123456789",
}
SAMPLE = {
    "character": "Ashblade",
    "moment": "victory",
    "en": "I made it through. Until next time.",
    "ja": "切り抜けたぞ。また会おう。",
}


def envelope(method, params):
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}


def send(data):
    return envelope(
        "SendMessage",
        {
            "message": {
                "messageId": str(uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": data}],
            },
            "configuration": {"returnImmediately": False},
        },
    )


def config(database: Path):
    return ReviewSettings(token=SecretStr(AUTH["Authorization"][7:]), database=database)


def test_localization_rpc_discovers_reviews_and_reloads_task(tmp_path):
    settings = config(tmp_path / "review.sqlite3")
    with TestClient(create_app(settings)) as client:
        card = client.get("/.well-known/agent-card.json").json()
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        message = send(
            {"lines": [SAMPLE, {**SAMPLE, "en": "Vettu.", "ja": "English only."}]}
        )
        assert client.post("/a2a", json=message).status_code == 401
        response = client.post("/a2a", headers=AUTH, json=message).json()
        assert response["id"] == message["id"]
        task = response["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        artifact = task["artifacts"][0]["parts"][0]["data"]
        assert artifact["status"] == "revision_needed"
        assert artifact["findings"][1]["issues"] == [
            "invalid_japanese",
            "legacy_strike_term",
        ]

    with TestClient(create_app(settings)) as restarted:
        get_request = envelope("GetTask", {"id": task["id"], "historyLength": 10})
        assert restarted.post("/a2a", json=get_request).status_code == 401
        loaded = restarted.post("/a2a", headers=AUTH, json=get_request).json()["result"]
        assert loaded["artifacts"] == task["artifacts"]
        assert "history" not in loaded


def test_localization_rpc_distinguishes_policy_findings_and_invalid_payload(tmp_path):
    settings = config(tmp_path / "review.sqlite3")
    with TestClient(create_app(settings)) as client:
        ready = client.post("/a2a", headers=AUTH, json=send({"lines": [SAMPLE]})).json()
        assert (
            ready["result"]["task"]["artifacts"][0]["parts"][0]["data"]["status"]
            == "ready_for_editor"
        )
        rejected = client.post(
            "/a2a",
            headers=AUTH,
            json=send({"lines": [{**SAMPLE, "player_id": "extra"}]}),
        ).json()
        assert rejected["result"]["task"]["status"]["state"] == "TASK_STATE_REJECTED"
