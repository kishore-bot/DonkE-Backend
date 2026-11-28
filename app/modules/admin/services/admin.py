from datetime import UTC, datetime, timedelta
from secrets import compare_digest
from uuid import UUID

from anyio import CapacityLimiter, to_thread
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.platform import Platform
from app.core.tokens import new_token, token_digest
from app.modules.admin.helpers import totp, vault
from app.modules.admin.helpers.errors import invalid_admin
from app.modules.admin.helpers.passwords import DUMMY_HASH, HASHER, password_matches
from app.modules.admin.models.admin_audit import AdminAudit
from app.modules.admin.models.admin_session import AdminSession
from app.modules.admin.models.admin_user import AdminUser
from app.modules.admin.repositories import admins
from app.modules.admin.schemas.audit import AuditEntry
from app.modules.admin.schemas.auth import AdminLogin, AdminProfile, Role, TotpSetup
from app.modules.admin.services.audit import admin_write


class AdminService:
    def __init__(self, platform: Platform):
        self.platform = platform
        self.limiter = CapacityLimiter(4)

    async def create_account(
        self, username: str, password: str, role: Role, request_id: UUID
    ) -> AdminProfile:
        async with self.platform.sessions.begin() as db:
            account = await self._insert_account(db, username, password, role)
            db.add(
                AdminAudit(
                    admin_id=account.id,
                    action="create_account",
                    reason="Operator CLI",
                    request_id=request_id,
                )
            )
            return AdminProfile.model_validate(account)

    async def create_console_account(
        self,
        username: str,
        password: str,
        role: Role,
        *,
        cookie: str | None,
        csrf: str | None,
        request_id: UUID | None,
        reason: str,
    ) -> AdminProfile:
        async with admin_write(
            self.platform, cookie, csrf, request_id, "create_admin", reason
        ) as db:
            account = await self._insert_account(db, username, password, role)
            return AdminProfile.model_validate(account)

    async def _insert_account(
        self, db: AsyncSession, username: str, password: str, role: Role
    ) -> AdminUser:
        password_hash = await to_thread.run_sync(
            HASHER.hash, password, limiter=self.limiter
        )
        account = AdminUser(username=username, password_hash=password_hash, role=role)
        db.add(account)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise AppError(
                409, "admin_username_taken", "Admin username already exists"
            ) from exc
        return account

    async def second_factor(self, user: AdminUser, code: str | None) -> None:
        if not user.totp_enabled or user.totp_secret is None:
            return
        if code is None:
            raise AppError(401, "totp_required", "Enter your authenticator code")
        secret = vault.unseal(self.platform.settings, user.id, user.totp_secret)
        step = totp.matching_step(secret, code, datetime.now(UTC).timestamp())
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
            candidate = await admins.by_username(db, username)
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
            row = await admins.session_owner(
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
            row = await admins.session_owner(
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
            secret = totp.new_secret()
            # Stored sealed; the plain secret is shown once, to this admin.
            user.totp_secret = vault.seal(self.platform.settings, user.id, secret)
            return TotpSetup(
                secret=secret, uri=totp.provisioning_uri(secret, user.username)
            )

    async def totp_confirm(
        self, cookie: str | None, csrf: str | None, code: str, request_id: UUID
    ) -> AdminProfile:
        async with self.platform.sessions.begin() as db:
            user = await self.writer(db, cookie, csrf)
            sealed = user.totp_secret
            secret = (
                vault.unseal(self.platform.settings, user.id, sealed)
                if sealed
                else None
            )
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
        row = await admins.session_owner(
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
                AuditEntry.model_validate(row) for row in await admins.recent_audit(db)
            ]
