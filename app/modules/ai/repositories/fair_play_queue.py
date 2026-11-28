from pathlib import Path
from typing import cast

from app.core.platform import Platform
from app.modules.matches.helpers.keys import pending_analysis_key

QUEUE_SCORE = 50


BATCH = 3


LEASE_SECONDS = 300


CLAIM = Path(__file__).with_name("claim_analysis.lua").read_text(encoding="utf-8")


def pending_key(platform: Platform) -> str:
    return pending_analysis_key(platform)


async def claim_pending(platform: Platform, limit: int = BATCH) -> list[str]:
    """Lease up to `limit` due matches and set their retry times atomically."""
    if limit <= 0:
        return []
    pending = cast(
        "list[str | bytes]",
        await platform.redis.execute_command(
            "EVAL", CLAIM, 1, pending_key(platform), limit, LEASE_SECONDS * 1_000
        ),
    )
    return [item.decode() if isinstance(item, bytes) else item for item in pending]
