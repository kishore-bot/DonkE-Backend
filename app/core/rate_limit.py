from ipaddress import IPv4Network, IPv6Network, ip_address
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


class FailureLimit:
    """Counts only failed attempts. `check` refuses once `maximum` failures are
    recorded inside the window, `fail` records one, and `clear` forgets them."""

    def __init__(
        self, platform: Platform, action: str, scope: str, maximum: int, seconds: int
    ):
        self.platform, self.maximum, self.seconds = platform, maximum, seconds
        self.key = f"{platform.settings.redis_prefix}:fail:{action}:{scope}"

    async def check(self) -> None:
        failures = await self.platform.redis.get(self.key)
        if failures is not None and int(failures) >= self.maximum:
            raise AppError(429, "rate_limited", "Too many attempts. Try again later")

    async def fail(self) -> None:
        await self.platform.redis.execute_command(
            "EVAL", COUNTER, 1, self.key, self.seconds
        )

    async def clear(self) -> None:
        await self.platform.redis.delete(self.key)


def client_host(request: Request) -> str:
    """The caller's IP. X-Forwarded-For is honoured only when the direct peer
    is a configured trusted proxy, walking right to left to the first address
    that is not a proxy, so clients cannot spoof it from outside."""
    peer = request.client.host if request.client else "unknown"
    trusted = getattr(request.app.state, "trusted_proxies", ())
    if not trusted or not _within(peer, trusted):
        return peer
    hops = [
        hop.strip()
        for hop in request.headers.get("x-forwarded-for", "").split(",")
        if hop.strip()
    ]
    for hop in reversed(hops):
        if not _within(hop, trusted):
            return hop
    return peer


def _within(address: str, networks: tuple[IPv4Network | IPv6Network, ...]) -> bool:
    try:
        ip = ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)
