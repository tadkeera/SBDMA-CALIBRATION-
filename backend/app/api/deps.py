"""FastAPI dependencies: DB session, principal resolution, request context."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import (
    AuthenticationError,
    MfaEnrolmentRequiredError,
    PasswordChangeRequiredError,
)
from app.core.logging import department_ctx, user_ctx
from app.core.rbac import Principal
from app.core.security import decode_token
from app.models.rbac import RefreshSession
from app.services.auth_service import load_principal

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Endpoints reachable while a role-mandated second factor is not yet enrolled.
MFA_ENROLMENT_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/mfa",
        "/api/v1/auth/mfa/enrol",
        "/api/v1/auth/mfa/activate",
        "/api/v1/auth/mfa/qr.svg",
        "/api/v1/auth/mfa/recovery",
    }
)

#: The only endpoints reachable while a forced password change is outstanding.
PASSWORD_CHANGE_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/change-password",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
    }
)


def _bearer(request: Request) -> str:
    """Explicit Authorization wins; otherwise fall back to the httpOnly cookie.

    The browser never has to expose the token to JavaScript, while API clients
    and tests can address several identities from one process.
    """
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    cookie_token = request.cookies.get("sbdma_access")
    if cookie_token:
        return cookie_token
    raise AuthenticationError(
        message_ar="يلزم تسجيل الدخول", message_en="Authentication required"
    )


async def get_principal(request: Request, session: SessionDep) -> Principal:
    token = _bearer(request)
    try:
        payload = decode_token(token, expected_kind="access")
    except ValueError as exc:
        raise AuthenticationError(
            message_ar="جلسة غير صالحة أو منتهية",
            message_en="Invalid or expired session",
        ) from exc

    principal = await load_principal(session, uuid.UUID(payload["sub"]))
    principal.session_id = payload.get("sid")

    # A revoked session must stop working immediately, not when the JWT expires.
    if principal.session_id:
        try:
            session_uuid = uuid.UUID(str(principal.session_id))
        except ValueError:
            raise AuthenticationError(
                message_ar="جلسة غير صالحة",
                message_en="Invalid session identifier",
            ) from None
        revoked = (
            await session.execute(
                select(RefreshSession.revoked_at).where(RefreshSession.id == session_uuid)
            )
        ).scalar_one_or_none()
        if revoked is not None:
            raise AuthenticationError(
                message_ar="انتهت الجلسة — أُبطلت من مسؤول الحسابات",
                message_en="Session revoked",
            )

    # An account still holding an administrator-issued password may do exactly
    # two things: identify itself and replace that password. Everything else is
    # refused, because a record signed with a credential the administrator knows
    # is not attributable to the signer.
    #
    # The two gates are listed explicitly (rather than one refusing "everything
    # else") because a new account can need *both* at once: an administrator-issued
    # password on a role that also mandates a second factor. Refusing each gate every
    # path the other one needs left such an account frozen — it could not set the
    # password because enrolment came first and could not enrol because the password
    # came first. The refusal below is therefore subtracted, and the order in which the
    # screens ask for the two is a presentation choice, not a deadlock.
    if principal.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        if request.url.path not in MFA_ENROLMENT_ALLOWED_PATHS:
            raise PasswordChangeRequiredError()

    # Same idea for a missing second factor on a role that requires one: the user
    # can reach enrolment and nothing else, so they are never stranded.
    if principal.mfa_enrolment_required and request.url.path not in MFA_ENROLMENT_ALLOWED_PATHS:
        if request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            raise MfaEnrolmentRequiredError()

    request.state.principal = principal
    user_ctx.set(principal.username)
    department_ctx.set(str(principal.department_id or "-"))
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_optional_principal(request: Request, session: SessionDep) -> Principal | None:
    try:
        return await get_principal(request, session)
    except AuthenticationError:
        return None


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """Optional on reads; routers enforce it for state-changing POSTs."""
    return idempotency_key
