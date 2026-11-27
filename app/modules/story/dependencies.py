from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends


def utc_now() -> datetime:
    return datetime.now(UTC)


async def get_story_clock() -> Callable[[], datetime]:
    return utc_now


StoryClock = Annotated[Callable[[], datetime], Depends(get_story_clock)]
