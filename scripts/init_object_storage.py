"""Prepare the configured object store for season media.

Creates the bucket when missing and allows signed GET reads from the browser
origins in DONKE_SEASON_MEDIA_CORS_ORIGINS (comma separated). Works with any
backend registered in app.core.storage. Safe to rerun.
"""

import asyncio
import os
import sys

from app.core.config import Settings
from app.core.storage import build_storage


async def prepare(seconds: int = 60) -> None:
    storage = build_storage(Settings())
    if storage is None:
        print("No object storage configured; nothing to prepare", file=sys.stderr)
        return
    origins = [
        origin.strip()
        for origin in os.environ.get("DONKE_SEASON_MEDIA_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    # The store container may still be starting.
    async with asyncio.timeout(seconds):
        while True:
            try:
                await storage.prepare(origins)
                break
            except Exception as error:
                print(
                    f"Waiting for object storage ({type(error).__name__})",
                    file=sys.stderr,
                )
                await asyncio.sleep(1)
    print("Object storage is ready", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(prepare())
