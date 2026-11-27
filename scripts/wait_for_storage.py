"""Wait for Compose storage before replacing this process with the service."""

import argparse
import asyncio
import os

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import open_platform


async def wait_for_storage() -> None:
    async with asyncio.timeout(120), open_platform(Settings()) as platform:
        while True:
            try:
                await platform.ready()
            except AppError, OSError, RedisError, SQLAlchemyError:
                await asyncio.sleep(1)
            else:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("Supply a service command")
    try:
        asyncio.run(wait_for_storage())
    except TimeoutError:
        parser.exit(
            1,
            "Storage did not become ready. Check database initialization and store logs.\n",
        )
    os.execvp(args.command[0], args.command)  # noqa: S606 - replace this process with the service


if __name__ == "__main__":
    main()
