"""Authentication: login, lockout, refresh rotation, logout, session revocation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    AccountLockedError,
    AuthenticationError,
    MfaEnrolmentRequiredError,
    SecondFactorRequiredError,
    ValidationFailedError,
)
from app.core.logging import get_logger
from app.core.mfa import (
    SecretUndecryptable,
    decrypt_secret,
    enforced_roles,
    mfa_required_for,
    verify_code,
)
from app.core.rbac import ROLE_PERMISSIONS, Principal
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    password_strength_errors,
    sha256_hex,
    verify_password,
)
from app.models.rbac import LabDepartment, RefreshSession, User
from app.services.audit_service import AuditService

log = get_logger("sbdma.auth")


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.audit = AuditService(session)

    async def _find_user(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def authenticate(
        self,
        *,
        username: str,
        password: str,
        totp_code: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, Principal, dict[str, str]]:
        user = await self._find_user(username)
        now = datetime.now(timezone.utc)

        # Uniform failure message: never reveal whether the account exists.
        if user is None:
            await self.audit.record(
                action="LOGIN_FAILED",
                entity_type="user",
                entity_id="unknown",
                actor_label=username,
                reason="unknown username",
                ip_address=ip,
            )
            # Commit before raising: the request session is rolled back on
            # exception, and an unrecorded denial is not an audit trail.
            await self.session.commit()
            raise AuthenticationError()

        if user.locked_until and user.locked_until > now:
            raise AccountLockedError()

        if not user.is_active or user.deleted_at is not None:
            await self.audit.record(
                action="LOGIN_BLOCKED_INACTIVE",
                entity_type="user",
                entity_id=user.id,
                actor_label=user.username,
                reason="account disabled",
                ip_address=ip,
            )
            await self.session.commit()
            raise AuthenticationError(
                message_ar="الحساب معطل — راجع مسؤول النظام",
                message_en="Account disabled — contact the system administrator",
            )

        valid, rehash = verify_password(password, user.password_hash)
        if not valid:
            user.failed_login_count += 1
            if user.failed_login_count >= self.settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
                user.failed_login_count = 0
                await self.audit.record(
                    action="ACCOUNT_LOCKED",
                    entity_type="user",
                    entity_id=user.id,
                    actor_label=user.username,
                    reason=f"locked after {self.settings.max_failed_logins} failed attempts",
                    ip_address=ip,
                )
            await self.audit.record(
                action="LOGIN_FAILED",
                entity_type="user",
                entity_id=user.id,
                actor_label=user.username,
                reason="wrong password",
                ip_address=ip,
            )
            # Commit (not flush): get_session rolls back on exception, so a
            # flushed-but-not-committed counter would be discarded and the
            # account lockout could never engage. See tests/test_api_users.py.
            await self.session.commit()
            raise AuthenticationError()

        if rehash:
            user.password_hash = rehash

        # ── second factor (21 CFR Part 11.200(a)(1)(i)) ──────────────────────
        # Checked *after* the password so a wrong code never reveals that the
        # password was right, and before the counters are cleared so a failed
        # code counts toward the same lockout as a failed password.
        roles = [r.code for r in user.roles] or ["VIEWER"]
        if user.totp_enabled:
            matched = None
            if totp_code:
                try:
                    secret = decrypt_secret(user.totp_secret or "")
                except SecretUndecryptable:
                    await self.audit.record(
                        action="MFA_SECRET_UNREADABLE",
                        entity_type="user",
                        entity_id=user.id,
                        actor_label=user.username,
                        reason="stored TOTP secret could not be decrypted",
                        ip_address=ip,
                    )
                    await self.session.commit()
                    raise AuthenticationError(
                        message_ar="تعذّر التحقق من العامل الثاني — راجع مسؤول النظام",
                        message_en="The second factor could not be verified — contact the administrator",
                    ) from None
                matched = verify_code(secret, totp_code, last_used_counter=user.totp_last_counter)
                if matched is not None:
                    user.totp_last_counter = matched

            if matched is None:
                user.failed_login_count += 1
                if user.failed_login_count >= self.settings.max_failed_logins:
                    user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
                    user.failed_login_count = 0
                await self.audit.record(
                    action="MFA_FAILED",
                    entity_type="user",
                    entity_id=user.id,
                    actor_label=user.username,
                    reason="missing or invalid second factor" if totp_code else "second factor missing",
                    ip_address=ip,
                )
                await self.session.commit()
                raise SecondFactorRequiredError()
        # The role mandates a second factor and this account has not enrolled.
        # Refusing to sign in at all would strand the user with no way to enrol,
        # so a session is issued that reaches nothing but the enrolment routes —
        # the same shape as the forced-password-change gate. See deps.py.
        enrolment_pending = not user.totp_enabled and mfa_required_for(roles)
        if enrolment_pending:
            await self.audit.record(
                action="MFA_ENROLMENT_REQUIRED",
                entity_type="user",
                entity_id=user.id,
                actor_label=user.username,
                reason=f"role mandates a second factor: {sorted(set(roles) & enforced_roles())}",
                ip_address=ip,
            )

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now

        principal = Principal.build(
            user_id=user.id,
            username=user.username,
            roles=roles,
            department_id=user.department_id,
            must_change_password=user.must_change_password,
            mfa_enrolment_required=enrolment_pending,
        )

        tokens = await self._issue_tokens(user, principal, ip=ip, user_agent=user_agent)

        await self.audit.record(
            action="LOGIN_SUCCESS",
            entity_type="user",
            entity_id=user.id,
            actor_label=user.username,
            actor_id=user.id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            reason="successful sign-in",
            ip_address=ip,
        )
        await self.session.flush()
        return user, principal, tokens

    async def _issue_tokens(
        self,
        user: User,
        principal: Principal,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> dict[str, str]:
        settings = self.settings
        # The access token carries the id of the refresh-session row it belongs to.
        # Without this link, revoking a session would leave the already-issued
        # access tokens working until they expire — a "revoked" session that is
        # still usable is worse than no revocation at all.
        refresh_session_id = uuid.uuid4()
        access = create_token(
            str(user.id),
            "access",
            role=principal.primary_role,
            department_id=str(user.department_id) if user.department_id else None,
            extra={"roles": principal.roles, "sid": str(refresh_session_id)},
        )
        refresh = create_token(
            str(user.id),
            "refresh",
            role=principal.primary_role,
            extra={"sid": str(refresh_session_id)},
        )
        now = datetime.now(timezone.utc)
        self.session.add(
            RefreshSession(
                id=refresh_session_id,
                user_id=user.id,
                token_hash=sha256_hex(refresh),
                issued_at=now,
                expires_at=now + timedelta(days=settings.jwt_refresh_ttl_days),
                user_agent=(user_agent or "")[:255] or None,
                ip_address=ip,
            )
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": str(settings.jwt_access_ttl_minutes * 60),
            "refresh_expires_in": str(settings.jwt_refresh_ttl_days * 86400),
        }

    async def refresh(self, refresh_token: str) -> dict[str, str]:
        try:
            payload = decode_token(refresh_token, expected_kind="refresh")
        except ValueError:
            raise AuthenticationError(
                message_ar="جلسة غير صالحة — يلزم إعادة تسجيل الدخول",
                message_en="Invalid session — please sign in again",
            ) from None

        token_hash = sha256_hex(refresh_token)
        row = (
            await self.session.execute(
                select(RefreshSession).where(RefreshSession.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None or row.expires_at < datetime.now(timezone.utc):
            raise AuthenticationError(
                message_ar="جلسة منتهية أو ملغاة", message_en="Session expired or revoked"
            )

        user = await self.session.get(User, uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError()

        # rotation: the presented token is single-use
        row.revoked_at = datetime.now(timezone.utc)
        principal = Principal.build(
            user_id=user.id,
            username=user.username,
            roles=[r.code for r in user.roles] or ["VIEWER"],
            department_id=user.department_id,
        )
        return await self._issue_tokens(user, principal, ip=row.ip_address, user_agent=row.user_agent)

    async def logout(self, *, user_id: uuid.UUID, refresh_token: str | None, ip: str | None = None) -> None:
        """Revoke the presented refresh session, or every session for the user."""
        stmt = select(RefreshSession).where(
            RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
        )
        if refresh_token:
            stmt = stmt.where(RefreshSession.token_hash == sha256_hex(refresh_token))
        rows = (await self.session.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.revoked_at = now
        await self.audit.record(
            action="LOGOUT",
            entity_type="user",
            entity_id=user_id,
            actor_label=str(user_id),
            actor_id=user_id,
            reason=f"revoked {len(rows)} session(s)",
            ip_address=ip,
        )

    async def change_password(
        self, *, user_id: uuid.UUID, current_password: str, new_password: str, reason: str
    ) -> None:
        user = await self.session.get(User, user_id)
        if user is None:
            raise AuthenticationError()
        valid, _ = verify_password(current_password, user.password_hash)
        if not valid:
            raise AuthenticationError(
                message_ar="كلمة المرور الحالية غير صحيحة",
                message_en="Current password is incorrect",
            )
        problems = password_strength_errors(new_password)
        if problems:
            raise ValidationFailedError(details={"password_rules": problems})

        user.password_hash = hash_password(new_password)
        user.must_change_password = False

        # every existing session is invalidated on password change
        rows = (
            await self.session.execute(
                select(RefreshSession).where(
                    RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
                )
            )
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.revoked_at = now

        await self.audit.record(
            action="PASSWORD_CHANGED",
            entity_type="user",
            entity_id=user_id,
            actor_label=user.username,
            actor_id=user_id,
            reason=reason,
        )


async def load_principal(session: AsyncSession, user_id: uuid.UUID) -> Principal:
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError()
    roles = [r.code for r in user.roles] or ["VIEWER"]
    return Principal.build(
        user_id=user.id,
        username=user.username,
        roles=roles,
        department_id=user.department_id,
        must_change_password=user.must_change_password,
        # recomputed per request so enrolment takes effect without re-login
        mfa_enrolment_required=not user.totp_enabled and mfa_required_for(roles),
    )


def permissions_for_roles(roles: list[str]) -> list[str]:
    perms: set[str] = set()
    for role in roles:
        perms.update(ROLE_PERMISSIONS.get(role, ()))
    return sorted(perms)
