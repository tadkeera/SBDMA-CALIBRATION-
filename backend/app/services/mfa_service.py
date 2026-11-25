"""Enrolment, activation, recovery and disabling of the second factor.

Split from ``AuthService`` because this is about *managing* the credential, not
about using it at sign-in. The ordering matters:

* ``begin_enrolment`` generates a **pending** secret and returns it once. It does
  not set ``totp_enabled`` — a QR that was mis-scanned must not lock the account.
* ``activate`` requires a valid code, which is the only proof that the
  authenticator and the server share the same secret.
* ``disable`` requires the password *and* a valid code, because dropping the
  second factor is what an attacker holding a stolen password would do first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError, ValidationFailedError
from app.core.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    match_recovery_code,
    new_secret,
    provisioning_uri,
    verify_code,
)
from app.core.rbac import Principal
from app.core.security import verify_password
from app.models.rbac import User
from app.services.audit_service import AuditService


class MfaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise AuthenticationError()
        return user

    # ─────────────────────────── enrolment ────────────────────────────────── #

    async def begin_enrolment(self, principal: Principal) -> dict:
        """Issue a pending secret and its provisioning URI.

        Re-running this while an enrolment is pending simply replaces the pending
        secret — no authenticator has proved possession of it yet, so nothing is
        lost. Running it on an *active* enrolment is refused: silently replacing a
        working second factor would let a stolen session swap the attacker's
        authenticator in.
        """
        user = await self._user(principal.user_id)
        if user.totp_enabled:
            raise ConflictError(
                message_ar="التحقق بخطوتين مفعّل مسبقاً — أوقفه أولاً لإعادة التسجيل",
                message_en="Two-step verification is already active — disable it before re-enrolling",
            )

        secret = new_secret()
        user.totp_secret = encrypt_secret(secret)
        user.totp_enabled = False
        user.totp_last_counter = None
        await self.audit.record(
            action="MFA_ENROLMENT_STARTED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=user.id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            reason="second-factor enrolment started",
        )
        return {
            "secret": secret,
            "otpauth_uri": provisioning_uri(secret, username=user.username),
            "digits": 6,
            "period_seconds": 30,
            "algorithm": "SHA1",
        }

    async def pending_uri(self, principal: Principal) -> str:
        """The otpauth:// URI for the pending enrolment (never re-issues it)."""
        user = await self._user(principal.user_id)
        if not user.totp_secret or user.totp_enabled:
            raise ValidationFailedError(
                message_ar="لا يوجد تسجيل قيد الانتظار",
                message_en="There is no pending enrolment",
            )
        return provisioning_uri(decrypt_secret(user.totp_secret), username=user.username)

    async def activate(self, principal: Principal, code: str, *, ip: str | None = None) -> dict:
        """Confirm possession of the pending secret and turn the factor on."""
        user = await self._user(principal.user_id)
        if user.totp_enabled:
            raise ConflictError(
                message_ar="التحقق بخطوتين مفعّل مسبقاً",
                message_en="Two-step verification is already active",
            )
        if not user.totp_secret:
            raise ValidationFailedError(
                message_ar="ابدأ التسجيل أولاً",
                message_en="Start enrolment before activating",
                field="code",
            )

        secret = decrypt_secret(user.totp_secret)
        matched = verify_code(secret, code, last_used_counter=None)
        if matched is None:
            await self.audit.record(
                action="MFA_ACTIVATION_FAILED",
                entity_type="user",
                entity_id=user.id,
                actor_label=principal.username,
                actor_id=user.id,
                reason="invalid code during enrolment",
                ip_address=ip,
            )
            await self.session.commit()
            raise ValidationFailedError(
                message_ar="الرمز غير صحيح — تأكد من ضبط ساعة الهاتف ثم أعد المحاولة",
                message_en="That code is not valid — check your phone's clock and try again",
                field="code",
            )

        plain_codes, hashes = generate_recovery_codes()
        user.totp_enabled = True
        user.totp_last_counter = matched
        user.totp_enrolled_at = datetime.now(timezone.utc)
        user.totp_recovery_hashes = hashes

        await self.audit.record(
            action="MFA_ENABLED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=user.id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            new_values={"recovery_codes_issued": len(plain_codes)},
            reason="second factor activated after successful code verification",
            ip_address=ip,
        )
        # Returned once and never again: only Argon2 hashes are stored.
        return {"enabled": True, "recovery_codes": plain_codes}

    # ──────────────────────────── disabling ───────────────────────────────── #

    async def disable(
        self, principal: Principal, *, password: str, code: str, ip: str | None = None
    ) -> dict:
        """Turn the factor off — password **and** a valid code are both required."""
        user = await self._user(principal.user_id)
        if not user.totp_enabled:
            raise ConflictError(
                message_ar="التحقق بخطوتين غير مفعّل أصلاً",
                message_en="Two-step verification is not active",
            )

        valid, _ = verify_password(password, user.password_hash)
        if not valid:
            await self.audit.record(
                action="MFA_DISABLE_FAILED",
                entity_type="user",
                entity_id=user.id,
                actor_label=principal.username,
                actor_id=user.id,
                reason="wrong password supplied when disabling MFA",
                ip_address=ip,
            )
            await self.session.commit()
            raise AuthenticationError()

        secret = decrypt_secret(user.totp_secret or "")
        matched = verify_code(secret, code, last_used_counter=user.totp_last_counter)
        if matched is None:
            await self.audit.record(
                action="MFA_DISABLE_FAILED",
                entity_type="user",
                entity_id=user.id,
                actor_label=principal.username,
                actor_id=user.id,
                reason="invalid code supplied when disabling MFA",
                ip_address=ip,
            )
            await self.session.commit()
            raise ValidationFailedError(
                message_ar="الرمز غير صحيح",
                message_en="That code is not valid",
                field="code",
            )

        user.totp_enabled = False
        user.totp_secret = None
        user.totp_last_counter = None
        user.totp_enrolled_at = None
        user.totp_recovery_hashes = None
        await self.audit.record(
            action="MFA_DISABLED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=user.id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            reason="second factor disabled by the account owner",
            ip_address=ip,
        )
        return {"enabled": False}

    # ──────────────────────────── recovery ────────────────────────────────── #

    async def redeem_recovery_code(
        self, *, username: str, password: str, code: str, ip: str | None = None
    ) -> User:
        """Sign-in path for a user who lost the authenticator.

        The password is still required (so a stolen sheet of recovery codes is
        useless alone), each code is consumed exactly once, and every remaining
        code is invalidated afterwards — the set is single-use as a whole.
        """
        from sqlalchemy import select

        user = (
            await self.session.execute(
                select(User).where(User.username == username.strip().lower(), User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None or not user.is_active or not user.totp_enabled:
            raise AuthenticationError()

        valid, _ = verify_password(password, user.password_hash)
        if not valid:
            raise AuthenticationError()

        hashes = list(user.totp_recovery_hashes or [])
        index = match_recovery_code(code, hashes)
        if index is None:
            await self.audit.record(
                action="MFA_RECOVERY_FAILED",
                entity_type="user",
                entity_id=user.id,
                actor_label=user.username,
                reason="invalid recovery code",
                ip_address=ip,
            )
            await self.session.commit()
            raise ValidationFailedError(
                message_ar="رمز الاسترداد غير صحيح أو مستخدم مسبقاً",
                message_en="That recovery code is invalid or already used",
                field="code",
            )

        hashes[index] = ""  # consumed
        user.totp_recovery_hashes = hashes
        # The authenticator is presumed lost: force re-enrolment so the old device
        # (which the attacker may hold) stops working.
        user.totp_enabled = False
        user.totp_secret = None
        user.totp_last_counter = None
        user.totp_enrolled_at = None

        await self.audit.record(
            action="MFA_RECOVERY_USED",
            entity_type="user",
            entity_id=user.id,
            actor_label=user.username,
            new_values={"remaining_codes": sum(1 for h in hashes if h), "mfa_reset": True},
            reason="recovery code redeemed; second factor reset for re-enrolment",
            ip_address=ip,
        )
        return user

    # ───────────────────────────── status ─────────────────────────────────── #

    async def status(self, principal: Principal) -> dict:
        user = await self._user(principal.user_id)
        return {
            "enabled": user.totp_enabled,
            "enrolled_at": user.totp_enrolled_at.isoformat() if user.totp_enrolled_at else None,
            "recovery_codes_remaining": sum(1 for h in (user.totp_recovery_hashes or []) if h),
            "pending_enrolment": bool(user.totp_secret) and not user.totp_enabled,
        }
