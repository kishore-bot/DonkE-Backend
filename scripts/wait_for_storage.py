"""Wait for Compose storage before replacing this process with the service."""

import argparse
import asyncio
import os

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import open_platform


async def wait_for_storage(*, migrate: bool) -> None:
    async with asyncio.timeout(120), open_platform(Settings()) as platform:
        while True:
            try:
                if migrate:
                    async with platform.engine.connect() as connection:
                        await connection.execute(text("SELECT 1"))
                else:
                    await platform.ready()
            except AppError, OSError, RedisError, SQLAlchemyError:
                await asyncio.sleep(1)
            else:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("Supply a service command")
    try:
        asyncio.run(wait_for_storage(migrate=args.migrate))
    except TimeoutError:
        parser.exit(
            1, "Storage did not become ready. Check the migration and store logs.\n"
        )
    os.execvp(args.command[0], args.command)


if __name__ == "__main__":
    main()
