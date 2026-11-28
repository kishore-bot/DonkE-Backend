import re
from functools import partial
from threading import Lock
from time import monotonic
from typing import Any, Protocol

from anyio import CapacityLimiter, to_thread
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token
from requests import Session

from app.core.errors import AppError

MAX_AGE = re.compile(r"max-age=(\d+)")


class CachedCerts:
    """google-auth fetches Google's signing certificates on every verification.
    This transport reuses one connection pool and serves the certificate
    response from memory for the max-age Google sends (usually hours)."""

    def __init__(self) -> None:
        self.transport = Request(session=Session())
        self.lock = Lock()
        self.cached: tuple[str, Any, float] | None = None

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> Any:
        with self.lock:
            cached = self.cached
        if cached and cached[0] == url and monotonic() < cached[2]:
            return cached[1]
        response = self.transport(url, method=method, **{**kwargs, "timeout": 4})
        match = MAX_AGE.search(response.headers.get("cache-control", ""))
        if method == "GET" and response.status == 200 and match:
            with self.lock:
                self.cached = (url, response, monotonic() + int(match.group(1)))
        return response


class GoogleIdentity(Protocol):
    async def verify(self, token: str) -> str: ...


class GoogleVerifier:
    def __init__(self, audience: str | None):
        self.audience = audience
        self.limiter = CapacityLimiter(8)
        self.certs = CachedCerts()

    async def verify(self, token: str) -> str:
        if not self.audience:
            raise AppError(503, "google_unavailable", "Google sign-in is unavailable")
        try:
            claims = await to_thread.run_sync(
                partial(verify_oauth2_token, token, self.certs, self.audience),
                limiter=self.limiter,
            )
        except TransportError as exc:
            raise AppError(
                503, "google_unavailable", "Google sign-in is unavailable"
            ) from exc
        except (GoogleAuthError, ValueError) as exc:
            raise AppError(
                401, "invalid_google_token", "Google could not verify this sign-in"
            ) from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise AppError(
                401, "invalid_google_token", "Google could not verify this sign-in"
            )
        return subject
