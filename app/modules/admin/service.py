from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from secrets import compare_digest
from uuid import UUID, uuid4

from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.core.tokens import new_token, token_digest
from app.modules.admin import repository, totp
from app.modules.admin.models import AdminAudit, AdminSession, AdminUser
from app.modules.admin.schemas import (
    AdminLogin,
    AdminProfile,
    AuditEntry,
    Role,
    TotpSetup,
)

HASHER = PasswordHasher()
# Verification cost for a missing username. This hash is never attached to an account.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQyNGNoYXJhY3Q$3pDP9EbuNjlGk1gUFYRhZbp8F0S6rxQ4T91c78Opy0s"


def password_matches(hash_value: str, password: str) -> bool:
    try:
        return HASHER.verify(hash_value, password)
    except InvalidHashError, VerificationError:
        return False


def invalid_admin() -> AppError:
    return AppError(401, "invalid_admin_session", "Admin authentication failed")


class AdminService:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.limiter = CapacityLimiter(4)

    async def create_account(
        self, username: str, password: str, role: Role, request_id: UUID
    ) -> AdminProfile:
        password_hash = await to_thread.run_sync(
            HASHER.hash, password, limiter=self.limiter
        )
        try:
            async with self.platform.sessions.begin() as db:
                account = AdminUser(
                    username=username, password_hash=password_hash, role=role
                )
                db.add(account)
                await db.flush()
                db.add(
                    AdminAudit(
                        admin_id=account.id,
                        action="create_account",
                        reason="Operator CLI",
                        request_id=request_id,
                    )
                )
                return AdminProfile.model_validate(account)
        except IntegrityError as exc:
            raise AppError(
                409, "admin_username_taken", "Admin username already exists"
            ) from exc

    async def second_factor(self, user: AdminUser, code: str | None) -> None:
        if not user.totp_enabled or user.totp_secret is None:
            return
        if code is None:
            raise AppError(401, "totp_required", "Enter your authenticator code")
        step = totp.matching_step(user.totp_secret, code, datetime.now(UTC).timestamp())
        used = f"{self.platform.settings.redis_prefix}:admin:totp:{user.id}:{step}"
        # Each code works once, even inside its 30-second window.
        if step is None or not await self.platform.redis.set(
            used, "1", nx=True, ex=120
        ):
            raise invalid_admin()

    async def sign_in(
        self,
        username: str,
        password: str,
        request_id: UUID,
        code: str | None = None,
    ) -> tuple[AdminLogin, str]:
        async with self.platform.sessions() as db:
            candidate = await repository.by_username(db, username)
            password_hash = candidate.password_hash if candidate else DUMMY_HASH
            account_id = candidate.id if candidate else None
        verified = await to_thread.run_sync(
            password_matches, password_hash, password, limiter=self.limiter
        )
        if not verified or account_id is None:
            raise invalid_admin()
        now = datetime.now(UTC)
        cookie, csrf_token = new_token(), new_token()
        async with self.platform.sessions.begin() as db:
            user = await db.scalar(
                select(AdminUser).where(AdminUser.id == account_id).with_for_update()
            )
            if user is None or not user.active or user.password_hash != password_hash:
                raise invalid_admin()
            await self.second_factor(user, code)
            user.last_login_at = now
            db.add(
                AdminSession(
                    token_digest=token_digest(cookie),
                    admin_id=user.id,
                    csrf_token=csrf_token,
                    expires_at=now
                    + timedelta(seconds=self.platform.settings.admin_session_seconds),
                )
            )
            db.add(
                AdminAudit(
                    admin_id=user.id,
                    action="login",
                    reason="Admin sign-in",
                    request_id=request_id,
                )
            )
            return AdminLogin(
                admin=AdminProfile.model_validate(user), csrf_token=csrf_token
            ), cookie

    async def current(self, cookie: str | None) -> AdminLogin:
        if not cookie or len(cookie) != 43:
            raise invalid_admin()
        async with self.platform.sessions() as db:
            row = await repository.session_owner(
                db, token_digest(cookie), datetime.now(UTC)
            )
            if row is None:
                raise invalid_admin()
            session, user = row
            return AdminLogin(
                admin=AdminProfile.model_validate(user), csrf_token=session.csrf_token
            )

    async def logout(
        self, cookie: str | None, csrf: str | None, request_id: UUID
    ) -> None:
        if not cookie or len(cookie) != 43:
            raise invalid_admin()
        async with self.platform.sessions.begin() as db:
            row = await repository.session_owner(
                db, token_digest(cookie), datetime.now(UTC), lock=True
            )
            if row is None:
                raise invalid_admin()
            session, user = row
            if not csrf or not compare_digest(
                session.csrf_token.encode(), csrf.encode()
            ):
                raise AppError(403, "csrf_required", "Send a valid CSRF token")
            await db.delete(session)
            db.add(
                AdminAudit(
                    admin_id=user.id,
                    action="logout",
                    reason="Admin sign-out",
                    request_id=request_id,
                )
            )

    async def totp_setup(self, cookie: str | None, csrf: str | None) -> TotpSetup:
        async with self.platform.sessions.begin() as db:
            user = await self.writer(db, cookie, csrf)
            if user.totp_enabled:
                raise AppError(409, "totp_enabled", "Two-factor sign-in is already on")
            secret = user.totp_secret = totp.new_secret()
            return TotpSetup(
                secret=secret, uri=totp.provisioning_uri(secret, user.username)
            )

    async def totp_confirm(
        self, cookie: str | None, csrf: str | None, code: str, request_id: UUID
    ) -> AdminProfile:
        async with self.platform.sessions.begin() as db:
            user = await self.writer(db, cookie, csrf)
            secret = user.totp_secret
            now = datetime.now(UTC).timestamp()
            if secret is None or totp.matching_step(secret, code, now) is None:
                raise AppError(422, "totp_invalid", "That code did not match")
            user.totp_enabled = True
            db.add(
                AdminAudit(
                    admin_id=user.id,
                    action="enable_totp",
                    reason="Two-factor sign-in enabled",
                    request_id=request_id,
                )
            )
            return AdminProfile.model_validate(user)

    async def writer(
        self, db: AsyncSession, cookie: str | None, csrf: str | None
    ) -> AdminUser:
        """The signed-in admin for a state-changing request (CSRF checked)."""
        if not cookie or len(cookie) != 43:
            raise invalid_admin()
        row = await repository.session_owner(
            db, token_digest(cookie), datetime.now(UTC), lock=True
        )
        if row is None:
            raise invalid_admin()
        session, user = row
        if not csrf or not compare_digest(session.csrf_token.encode(), csrf.encode()):
            raise AppError(403, "csrf_required", "Send a valid CSRF token")
        return user

    async def audit(self, cookie: str | None) -> list[AuditEntry]:
        identity = await self.current(cookie)
        if identity.admin.role != "admin":
            raise AppError(403, "admin_required", "Admin role required")
        async with self.platform.sessions() as db:
            return [
                AuditEntry.model_validate(row)
                for row in await repository.recent_audit(db)
            ]


@asynccontextmanager
async def admin_write(
    platform: Platform,
    cookie: str | None,
    csrf: str | None,
    request_id: UUID | None,
    action: str,
    reason: str,
    roles: tuple[str, ...] = ("admin",),
) -> AsyncIterator[AsyncSession]:
    async with platform.sessions.begin() as db:
        row = await repository.session_owner(
            db, token_digest(cookie or ""), datetime.now(UTC), lock=True
        )
        if row is None:
            raise AppError(401, "invalid_admin_session", "Admin authentication failed")
        session, admin = row
        if admin.role not in roles:
            raise AppError(403, "admin_required", "Admin role required")
        if csrf is None or not compare_digest(
            csrf.encode(), session.csrf_token.encode()
        ):
            raise AppError(403, "csrf_required", "Send a valid CSRF token")
        db.add(
            AdminAudit(
                admin_id=admin.id,
                action=action,
                reason=reason,
                request_id=request_id or uuid4(),
            )
        )
        yield db
