import argparse
import asyncio
import re
import sys
from getpass import getpass
from typing import cast
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import open_platform
from app.modules.admin.schemas import USERNAME, Role
from app.modules.admin.service import AdminService


async def create_admin(username: str, password: str, role: Role) -> None:
    async with open_platform(Settings()) as platform:
        admin = await AdminService(platform).create_account(
            username, password, role, uuid4()
        )
    print(f"Created {admin.role} account {admin.username}")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin")
    create.add_argument("--username", required=True)
    create.add_argument(
        "--role", choices=["viewer", "moderator", "admin"], required=True
    )
    args = parser.parse_args()
    if not re.fullmatch(USERNAME, args.username):
        parser.error("Use 3–48 lowercase letters, digits, dots, underscores or hyphens")
    if not sys.stdin.isatty():
        parser.error(
            "Run this command in an interactive terminal to enter the password"
        )
    password = getpass("Password: ")
    if not 12 <= len(password) <= 256:
        parser.error("Use a password between 12 and 256 characters")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        asyncio.run(create_admin(args.username, password, cast(Role, args.role)))
    except AppError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
