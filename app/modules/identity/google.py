from collections.abc import Mapping
from functools import partial
from typing import Protocol

from anyio import CapacityLimiter, to_thread
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token
from requests import Session

from app.core.errors import AppError


class GoogleIdentity(Protocol):
    async def verify(self, token: str) -> str: ...


class GoogleVerifier:
    def __init__(self, audience: str | None):
        self.audience = audience
        self.limiter = CapacityLimiter(8)

    async def verify(self, token: str) -> str:
        if not self.audience:
            raise AppError(503, "google_unavailable", "Google sign-in is unavailable")
        try:
            claims = await to_thread.run_sync(
                partial(self._verify, token, self.audience), limiter=self.limiter
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

    @staticmethod
    def _verify(token: str, audience: str) -> Mapping[str, object]:
        with Session() as session:
            transport = Request(session=session)
            return verify_oauth2_token(
                token, lambda *a, **kw: transport(*a, **{**kw, "timeout": 4}), audience
            )
