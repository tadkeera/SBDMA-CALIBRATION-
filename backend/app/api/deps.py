"""FastAPI dependencies: DB session, principal resolution, request context."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import AuthenticationError
from app.core.logging import department_ctx, user_ctx
from app.core.rbac import Principal
from app.core.security import decode_token
from app.services.auth_service import load_principal

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
