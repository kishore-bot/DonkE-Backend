from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from app.core.errors import AppError
from app.core.platform import Platform
from app.core.tokens import new_token, token_digest
from app.modules.identity.dto.principal import Principal
from app.modules.identity.helpers.errors import unauthorized
from app.modules.identity.models.player import Player
from app.modules.identity.models.player_session import PlayerSession
from app.modules.identity.models.refresh_token import RefreshToken
from app.modules.identity.repositories import players, sessions
from app.modules.identity.schemas.auth import SessionTokens
from app.modules.identity.schemas.profile import Language, Profile, ProfileUpdate


class IdentityService:
    def __init__(self, platform: Platform):
        self.platform = platform
        secret = platform.settings.auth_secret
        if secret is None:
            raise RuntimeError("Online identity requires an auth secret")
        self.secret = secret.get_secret_value()

    def _tokens(
        self, session: PlayerSession, refresh: str, now: datetime
    ) -> SessionTokens:
        expires = min(
            now + timedelta(seconds=self.platform.settings.access_seconds),
            session.expires_at,
        )
        access = jwt.encode(
            {
                "iss": "donke",
                "aud": "donke-player",
                "sub": str(session.player_id),
                "sid": str(session.id),
                "iat": now,
                "exp": expires,
            },
            self.secret,
            algorithm="HS256",
        )
        return SessionTokens(
            access_token=access,
            refresh_token=refresh,
            expires_in=int((expires - now).total_seconds()),
        )

    @staticmethod
    def _new_refresh(session_id: UUID) -> tuple[str, RefreshToken]:
        refresh = f"{session_id}.{new_token()}"
        return refresh, RefreshToken(
            session_id=session_id, digest=token_digest(refresh)
        )

    async def sign_in(self, subject: str) -> SessionTokens:
        now = datetime.now(UTC)
        async with self.platform.sessions.begin() as db:
            player = await players.find_or_create_player(db, subject)
            if not player.active:
                raise AppError(403, "player_inactive", "This account is inactive")
            session = PlayerSession(
                id=uuid4(),
                player_id=player.id,
                expires_at=now
                + timedelta(seconds=self.platform.settings.refresh_seconds),
            )
            refresh, row = self._new_refresh(session.id)
            db.add(session)
            await db.flush()
            db.add(row)
            return self._tokens(session, refresh, now)

    async def refresh(self, token: str) -> SessionTokens:
        try:
            session_id = UUID(token.split(".", maxsplit=1)[0])
        except ValueError as exc:
            raise unauthorized() from exc
        result = None
        async with self.platform.sessions.begin() as db:
            session = await sessions.locked_session(db, session_id)
            now = datetime.now(UTC)
            if (
                session is None
                or session.revoked_at is not None
                or session.expires_at <= now
            ):
                raise unauthorized()
            previous = await sessions.lookup_token(db, session.id, token_digest(token))
            if previous is None:
                raise unauthorized()
            player = await db.get(Player, session.player_id)
            grace = timedelta(
                seconds=self.platform.settings.refresh_reuse_grace_seconds
            )
            retry = previous.used_at is not None and now - previous.used_at <= grace
            if (
                player is None
                or not player.active
                or (previous.used_at is not None and not retry)
            ):
                # Reuse outside the grace window means the token leaked:
                # end the whole session.
                session.revoked_at = now
            else:
                # Consuming every outstanding token keeps one live chain: a grace
                # retry supersedes the replacement issued earlier, so a token
                # stolen inside the window cannot start a parallel chain, and
                # presenting a superseded token after the window revokes the session.
                await sessions.consume_outstanding(db, session.id, now)
                refresh, row = self._new_refresh(session.id)
                db.add(row)
                result = self._tokens(session, refresh, now)
        # A replay must commit the revocation before the unauthorized response is raised.
        if result is None:
            raise unauthorized()
        return result

    async def authenticate(self, token: str) -> Principal:
        if len(token) > 4096:
            raise unauthorized()
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                audience="donke-player",
                issuer="donke",
                options={"require": ["sub", "sid", "iat", "exp", "aud", "iss"]},
            )
            player_id, session_id = UUID(claims["sub"]), UUID(claims["sid"])
        except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError) as exc:
            raise unauthorized() from exc
        return await self.active_session(player_id, session_id)

    async def active_session(self, player_id: UUID, session_id: UUID) -> Principal:
        async with self.platform.sessions() as db:
            player = await players.active_player(
                db, player_id, session_id, datetime.now(UTC)
            )
            if player is None:
                raise unauthorized()
            return Principal(Profile.model_validate(player), session_id)

    async def logout(self, principal: Principal) -> None:
        async with self.platform.sessions.begin() as db:
            session = await sessions.locked_session(db, principal.session_id)
            if session is not None and session.revoked_at is None:
                session.revoked_at = datetime.now(UTC)

    async def set_language(self, principal: Principal, language: Language) -> Profile:
        return await self.update_profile(principal, ProfileUpdate(language=language))

    async def update_profile(
        self, principal: Principal, body: ProfileUpdate
    ) -> Profile:
        async with self.platform.sessions.begin() as db:
            player = await players.active_player(
                db, principal.profile.id, principal.session_id, datetime.now(UTC)
            )
            if player is None:
                raise unauthorized()
            if body.language is not None:
                player.language = body.language
            if body.voice is not None:
                player.voice = body.voice
            return Profile.model_validate(player)
