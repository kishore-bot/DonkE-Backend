"""Send a cue batch to the standalone A2A reviewer or retrieve an existing task."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from a2a.client import ClientConfig, create_client
from a2a.client.errors import A2AClientError
from a2a.helpers import get_data_parts, new_data_part, new_message
from a2a.types import a2a_pb2 as wire
from google.protobuf.json_format import ParseDict, ParseError
from httpx import AsyncClient, HTTPError

from app.services.localization_review import (
    RPC_PATH,
    ReviewBatch,
    ReviewReport,
    ReviewSettings,
)

MAX_BATCH_BYTES = 16_384


def read_batch(path: Path) -> ReviewBatch:
    with path.open("rb") as source:
        raw = source.read(MAX_BATCH_BYTES + 1)
    if len(raw) > MAX_BATCH_BYTES:
        raise ValueError("Cue batch exceeds 16 KiB")
    return ReviewBatch.model_validate_json(raw)


async def run(
    settings: ReviewSettings, batch: ReviewBatch | None, task_id: UUID | None
) -> dict:
    async with AsyncClient(trust_env=False, timeout=10) as discovery:
        response = await discovery.get(settings.origin + "/.well-known/agent-card.json")
        card = ParseDict(response.raise_for_status().json(), wire.AgentCard())
    expected = wire.AgentInterface(
        url=settings.origin + RPC_PATH,
        protocol_binding="JSONRPC",
        protocol_version="1.0",
    )
    if list(card.supported_interfaces) != [expected]:
        raise ValueError("The reviewer advertised an unexpected RPC endpoint")

    async with AsyncClient(
        headers={"Authorization": f"Bearer {settings.token.get_secret_value()}"},
        trust_env=False,
        timeout=10,
    ) as transport:
        remote = await create_client(
            card, ClientConfig(streaming=False, httpx_client=transport)
        )
        if task_id:
            task = await remote.get_task(
                wire.GetTaskRequest(id=str(task_id), history_length=0)
            )
        else:
            if batch is None:
                raise ValueError("Choose a cue batch or provide an existing task ID")
            request = wire.SendMessageRequest(
                message=new_message(
                    [new_data_part(batch.model_dump(mode="json"))],
                    role=wire.Role.ROLE_USER,
                ),
                configuration=wire.SendMessageConfiguration(history_length=0),
            )
            task = None
            async for result in remote.send_message(request):
                if result.HasField("task"):
                    task = result.task
            if task is None:
                raise ValueError("The reviewer returned no task")
    report = {
        "task_id": task.id,
        "state": wire.TaskState.Name(task.status.state),
    }
    if task.artifacts:
        findings = get_data_parts(task.artifacts[0].parts)
        if findings:
            report["review"] = ReviewReport.model_validate(findings[0]).model_dump(
                mode="json"
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--batch", type=Path, help="JSON file with one to eight cue pairs"
    )
    mode.add_argument("--task", type=UUID, help="Retrieve a prior task by ID")
    args = parser.parse_args()
    try:
        settings = ReviewSettings()  # pyright: ignore[reportCallIssue]
        batch = read_batch(args.batch) if args.batch is not None else None
        result = asyncio.run(run(settings, batch, args.task))
    except (OSError, ValueError, ParseError, HTTPError, A2AClientError) as exc:
        parser.exit(1, f"Review request stopped ({type(exc).__name__}).\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
