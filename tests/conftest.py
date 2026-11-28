import asyncio

import pytest
from sqlalchemy import delete, select

from app.core.platform import open_platform
from app.modules.progression.models import Season


@pytest.fixture(autouse=True)
def isolate_seasons(request):
    """Delete the seasons a database test creates, even when it fails.

    Season windows are global: the API refuses overlapping windows and
    progression credits whichever season covers a match. Seasons left behind
    by one run would break the next run on the same database. Rows that point
    at a season cascade with it. Tests without database settings are skipped
    by the `settings` fixture before this does anything.
    """
    if "settings" not in request.fixturenames:
        yield
        return
    settings = request.getfixturevalue("settings")

    async def existing() -> set:
        async with open_platform(settings) as platform, platform.sessions() as db:
            return set(await db.scalars(select(Season.id)))

    async def remove(before: set) -> None:
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            await db.execute(delete(Season).where(Season.id.not_in(before)))

    before = asyncio.run(existing())
    yield
    asyncio.run(remove(before))
