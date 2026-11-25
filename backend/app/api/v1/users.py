"""User administration: create, update, disable, reset, unlock, revoke sessions.

Every route requires ``users.manage``. The heavy lifting (escalation controls,
Part 11 separation of duties, audit entries) lives in ``UserService`` so the
rules cannot be bypassed by calling a different endpoint.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.schemas.auth import CreateUserRequest
from app.schemas.common import ok
from app.schemas.users import (
    ResetPasswordRequest,
    RevokeSessionsRequest,
    UnlockUserRequest,
    UpdateUserRequest,
    UserActionRequest,
)
from app.services.user_service import UserService, serialise_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", summary="سجل المستخدمين")
async def list_users(
    session: SessionDep,
    principal: PrincipalDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    active: bool | None = None,
    q: str | None = Query(default=None, max_length=80, description="بحث بالاسم أو البريد"),
):
    service = UserService(session)
    rows, total = await service.list_users(
        principal, page=page, page_size=page_size, active=active, query=q
    )
    return ok(
        [serialise_user(u) for u in rows],
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    )


@router.get("/roles", summary="الأدوار المتاحة وأولوياتها")
async def list_roles(session: SessionDep, principal: PrincipalDep):
    """Roles the caller may hand out, with the permissions each one carries.

    Returning only assignable roles keeps the client from offering an option the
    server will refuse — the authoritative check still runs on write.
    """
    from sqlalchemy import select

    from app.core.rbac import ROLE_PERMISSIONS, ROLE_RANK
    from app.models.rbac import Role

    principal.require("users.manage")
    rows = (await session.execute(select(Role).order_by(Role.rank))).scalars().all()
    my_rank = ROLE_RANK.get(principal.primary_role, 0)
    from app.services.user_service import role_confers_signoff

    return ok(
        [
            {
                "code": r.code,
                "name_ar": r.name_ar,
                "name_en": r.name_en,
                "rank": r.rank,
                "permissions": sorted(ROLE_PERMISSIONS.get(r.code, ())),
                "assignable": r.rank <= my_rank and not role_confers_signoff(r.code),
            }
            for r in rows
        ]
    )


@router.post("", summary="إنشاء حساب مستخدم", status_code=201)
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    reason: str = Query(min_length=8, max_length=500),
):
    """Create an account.

    The reason is a required query parameter because creating an identity is a
    GxP event: "who created this account, when, and why" must be answerable from
    the audit trail alone.
    """
    service = UserService(session)
    user = await service.create_user(
        principal,
        username=payload.username,
        email=str(payload.email),
        full_name_ar=payload.full_name_ar,
        full_name_en=payload.full_name_en,
        password=payload.password,
        roles=payload.roles,
        department_id=payload.department_id,
        reason=reason,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(serialise_user(user))


@router.patch("/{user_id}", summary="تحديث الأدوار أو القسم أو الحالة")
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = UserService(session)
    user = await service.update_user(
        principal,
        user_id,
        changes=payload.model_dump(exclude_unset=True, exclude={"reason"}),
        reason=payload.reason,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(serialise_user(user))


@router.post("/{user_id}/reset-password", summary="إعادة تعيين كلمة المرور")
async def reset_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = UserService(session)
    user = await service.reset_password(
        principal, user_id, password=payload.new_password, reason=payload.reason, ip=client_ip(request)
    )
    await session.commit()
    return ok(
        {
            "user_id": str(user.id),
            "must_change_password": True,
            "sessions_revoked": True,
            # the password itself is never echoed, logged or returned
        }
    )


@router.post("/{user_id}/unlock", summary="رفع القفل عن الحساب")
async def unlock_user(
    user_id: uuid.UUID,
    payload: UnlockUserRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = UserService(session)
    await service.unlock(principal, user_id, reason=payload.reason, ip=client_ip(request))
    await session.commit()
    return ok({"user_id": str(user_id), "is_locked": False})


@router.post("/{user_id}/revoke-sessions", summary="إبطال جلسات المستخدم")
async def revoke_sessions(
    user_id: uuid.UUID,
    payload: RevokeSessionsRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = UserService(session)
    count = await service.revoke_sessions(
        principal, user_id, reason=payload.reason, ip=client_ip(request)
    )
    await session.commit()
    return ok({"user_id": str(user_id), "revoked": count})
