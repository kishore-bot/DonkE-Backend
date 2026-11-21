from typing import cast

from fastapi import Request

from app.core.errors import AppError
from app.core.platform import Platform

COUNTER = """
local attempts = redis.call('INCR', KEYS[1])
if attempts == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return attempts
"""


async def limit(
    platform: Platform, action: str, scope: str, maximum: int, seconds: int
) -> None:
    key = f"{platform.settings.redis_prefix}:rate:{action}:{scope}"
    result = await platform.redis.execute_command("EVAL", COUNTER, 1, key, seconds)
    if cast("int", result) > maximum:
        raise AppError(429, "rate_limited", "Too many attempts. Try again later")


def client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"
