"""FastAPI dependencies: DB session, principal resolution, request context."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import AuthenticationError, PasswordChangeRequiredError
from app.core.logging import department_ctx, user_ctx
from app.core.rbac import Principal
from app.core.security import decode_token
from app.models.rbac import RefreshSession
from app.services.auth_service import load_principal

SessionDep = Annotated[AsyncSession, Depends(get_session)]

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
    if principal.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise PasswordChangeRequiredError()

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
