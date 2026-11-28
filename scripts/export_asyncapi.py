import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.modules.matches.schemas.socket import COMMAND
from app.modules.matches.schemas.state import EventBatch, PublicMatch


def contract() -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    messages = {}
    for name, adapter, direction in (
        ("command", COMMAND, "receive"),
        ("events", TypeAdapter(EventBatch), "send"),
        ("state_sync", TypeAdapter(PublicMatch), "send"),
    ):
        schema = adapter.json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        if direction == "send":
            schema.setdefault("properties", {})["type"] = {"const": name}
            schema.setdefault("required", []).append("type")
        messages[name] = {"name": name, "payload": schema}
    for message, extra in {
        "ack": {
            "version": {"type": "integer"},
            "sequence": {"type": "integer"},
            "request_id": {"type": "string", "format": "uuid"},
        },
        "error": {"code": {"type": "string"}},
        # Emotes and table chat from the social side feed; never changes the
        # game version. Hidden when the sender and viewer have a block.
        "feed": {
            "id": {"type": "string", "description": "Feed cursor"},
            "seat": {"type": "integer"},
            "kind": {"enum": ["emote", "chat"]},
            "value": {"type": "string"},
        },
        "pong": {},
        "left": {},
    }.items():
        messages[message] = {
            "name": message,
            "payload": {
                "type": "object",
                "properties": {"type": {"const": message}, **extra},
                "required": ["type", *extra],
            },
        }
    channel = "#/channels/match"
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "DonkE gameplay", "version": "0.1.0"},
        "defaultContentType": "application/json",
        "channels": {
            "match": {
                "address": "/api/v1/games/{game_id}/ws",
                "parameters": {
                    "game_id": {"description": "UUID assigned to the ready room"}
                },
                "description": (
                    "Authenticate with the Authorization Bearer header, or redeem a "
                    "single-use ticket from POST /api/v1/games/{game_id}/ws-ticket "
                    "using the donke.v1 and ticket.<value> WebSocket subprotocols. "
                    "The server negotiates donke.v1 for ticket connections. "
                    "Browser requests must originate from the configured public base "
                    "URL or, when unset, the request's own origin. "
                    "Resume with the after_sequence query parameter."
                ),
                "messages": {
                    name: {"$ref": f"#/components/messages/{name}"} for name in messages
                },
            }
        },
        "operations": {
            "receiveCommand": {
                "action": "receive",
                "channel": {"$ref": channel},
                "messages": [{"$ref": f"{channel}/messages/command"}],
            },
            "sendUpdates": {
                "action": "send",
                "channel": {"$ref": channel},
                "messages": [
                    {"$ref": f"{channel}/messages/{name}"}
                    for name in messages
                    if name != "command"
                ],
            },
        },
        "components": {"schemas": schemas, "messages": messages},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "docs/api/asyncapi.json"
    content = (
        json.dumps(contract(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            parser.exit(
                1, "Run python -m scripts.export_asyncapi to update the contract\n"
            )
    else:
        path.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
