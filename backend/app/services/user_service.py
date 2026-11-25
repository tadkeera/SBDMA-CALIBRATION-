"""User administration with privilege-escalation controls.

This is the one module where an administrator can hand out authority, so every
write is governed by constraints that are checked in the service *and* recorded
in the audit chain:

1. **No privilege escalation.** An actor may only grant permissions it holds and
   may only assign roles at or below its own rank (``Principal.assert_can_grant``
   / ``assert_role_assignable``).
2. **Part 11 separation of duties.** The roles that execute, review and approve a
   calibration must not be handed out by someone who would then be able to
   approve their own work. Administering accounts (``users.manage``) and holding
   an approval role are mutually exclusive: an administrator can neither create
   nor grant ``calibration.approve`` / ``limits.approve``. Real QA authority is
   established out of band by the system owner, not by the administrator who
   happens to be on duty.
3. **No self-service on your own authority.** You cannot change your own roles,
   re-activate your own disabled account, or reset your own password through the
   admin path (the audited ``/auth/change-password`` flow exists for that).
4. **Nothing is deleted.** Accounts are disabled, never removed, so historical
   signatures keep pointing at a real person.
5. **Nothing is un-audited.** Creation, every role/scope change, disable/enable,
   unlock and password reset write an explicit reason into the hash chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.rbac import ROLE_PERMISSIONS, ROLE_RANK, Principal
from app.core.security import hash_password, password_strength_errors
from app.models.rbac import LabDepartment, RefreshSession, Role, User
from app.services.audit_service import AuditService

#: Roles that confer approval authority over a calibration. Administering
#: accounts and holding these at the same time would let one person create an
#: approver account and sign their own work — a 21 CFR Part 11 violation.
SIGNOFF_PERMISSIONS: frozenset[str] = frozenset({"calibration.approve", "limits.approve"})


def role_confers_signoff(role_code: str) -> bool:
    return bool(SIGNOFF_PERMISSIONS & set(ROLE_PERMISSIONS.get(role_code, ())))


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ────────────────────────────── reads ────────────────────────────────── #

    async def _role_map(self) -> dict[str, Role]:
        rows = (await self.session.execute(select(Role))).scalars().all()
        return {r.code: r for r in rows}

    def _assert_roles_exist(self, codes: list[str], roles: dict[str, Role]) -> None:
        unknown = [c for c in codes if c not in roles]
        if unknown:
            raise ValidationFailedError(
                message_ar=f"أدوار غير معروفة: {', '.join(unknown)}",
                message_en=f"Unknown roles: {', '.join(unknown)}",
                field="roles",
            )

    def _assert_can_assign(self, principal: Principal, codes: list[str]) -> None:
        for code in codes:
            principal.assert_role_assignable(code)
            if role_confers_signoff(code):
                raise PermissionDeniedError(
                    message_ar=(
                        "لا يجوز لمن يدير الحسابات أن يمنح صلاحية اعتماد المعايرة — "
                        "فصل المهام يمنع أن ينشئ المسؤول حساباً يعتمد به عمله"
                    ),
                    message_en=(
                        "An account administrator may not grant calibration approval "
                        "authority: separation of duties forbids creating an approver "
                        "for your own work"
                    ),
                    field="roles",
                    details={"role": code, "blocked_permissions": sorted(SIGNOFF_PERMISSIONS)},
                )
            for permission in ROLE_PERMISSIONS.get(code, ()):
                # every permission the role carries must already be held by the actor
                principal.assert_can_grant(permission)

    async def _load_user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError(message_ar="المستخدم غير موجود", message_en="User not found")
        return user

    async def list_users(
        self,
        principal: Principal,
        *,
        page: int,
        page_size: int,
        active: bool | None = None,
        query: str | None = None,
    ) -> tuple[list[User], int]:
        principal.require("users.manage")
        conditions = [User.deleted_at.is_(None)]
        if not principal.is_supervisor():
            conditions.append(User.department_id == principal.department_id)
        if active is not None:
            conditions.append(User.is_active.is_(active))
        if query:
            needle = f"%{query.strip().lower()}%"
            conditions.append(
                func.lower(User.username).like(needle)
                | func.lower(User.email).like(needle)
                | User.full_name_ar.like(f"%{query.strip()}%")
                | func.lower(User.full_name_en).like(needle)
            )

        total = (
            await self.session.execute(select(func.count()).select_from(User).where(*conditions))
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(User)
                .where(*conditions)
                .order_by(User.username)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    # ────────────────────────────── writes ───────────────────────────────── #

    async def create_user(
        self,
        principal: Principal,
        *,
        username: str,
        email: str,
        full_name_ar: str,
        full_name_en: str,
        password: str,
        roles: list[str],
        department_id: uuid.UUID | None,
        reason: str,
        ip: str | None,
    ) -> User:
        principal.require("users.manage")
        roles = list(dict.fromkeys(roles))
        role_map = await self._role_map()
        self._assert_roles_exist(roles, role_map)
        self._assert_can_assign(principal, roles)

        if department_id is not None:
            department = await self.session.get(LabDepartment, department_id)
            if department is None or department.deleted_at is not None:
                raise ValidationFailedError(
                    message_ar="القسم غير موجود", message_en="Department not found", field="department_id"
                )
            principal.assert_department(department_id)

        problems = password_strength_errors(password)
        if problems:
            raise ValidationFailedError(details={"password_rules": problems}, field="password")

        username = username.strip().lower()
        email = email.strip().lower()
        existing = (
            await self.session.execute(
                select(User).where((User.username == username) | (User.email == email))
            )
        ).scalars().first()
        if existing is not None:
            raise ConflictError(
                message_ar="اسم المستخدم أو البريد مسجل مسبقاً",
                message_en="That username or e-mail is already registered",
                details={"username": username, "email": email},
            )

        user = User(
            id=uuid.uuid4(),
            department_id=department_id,
            username=username,
            email=email,
            full_name_ar=full_name_ar.strip(),
            full_name_en=full_name_en.strip(),
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=True,  # the administrator knows this password
            totp_enabled=False,
        )
        user.roles = [role_map[c] for c in roles]
        self.session.add(user)
        await self.session.flush()

        await self.audit.record(
            action="USER_CREATED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=department_id,
            new_values={
                "username": user.username,
                "email": user.email,
                "roles": roles,
                "must_change_password": True,
            },
            reason=reason,
            ip_address=ip,
        )
        return user

    async def update_user(
        self,
        principal: Principal,
        user_id: uuid.UUID,
        *,
        changes: dict,
        reason: str,
        ip: str | None,
    ) -> User:
        principal.require("users.manage")
        user = await self._load_user(user_id)
        principal.assert_department(user.department_id)

        # You cannot rewrite your own authority, and nobody can edit a peer admin.
        if user.id == principal.user_id and ({"roles", "is_active", "department_id"} & set(changes)):
            raise PermissionDeniedError(
                message_ar="لا يجوز تعديل أدوارك أو حالتك أو قسمك بنفسك",
                message_en="You may not change your own roles, active state or department",
                field=",".join(sorted({"roles", "is_active", "department_id"} & set(changes))),
            )

        role_map = await self._role_map()
        before: dict = {"roles": [r.code for r in user.roles], "is_active": user.is_active}

        if "roles" in changes and changes["roles"] is not None:
            roles = list(dict.fromkeys(changes["roles"]))
            if not roles:
                raise ValidationFailedError(
                    message_ar="يجب أن يبقى للمستخدم دور واحد على الأقل",
                    message_en="A user must keep at least one role",
                    field="roles",
                )
            self._assert_roles_exist(roles, role_map)
            self._assert_can_assign(principal, roles)
            user.roles = [role_map[c] for c in roles]

        if "is_active" in changes and changes["is_active"] is not None:
            if user.id == principal.user_id:
                raise PermissionDeniedError(
                    message_ar="لا يجوز تعطيل حسابك من خلال مسار الإدارة",
                    message_en="You may not disable your own account through the admin path",
                    field="is_active",
                )
            user.is_active = bool(changes["is_active"])
            if not user.is_active:
                await self._revoke_sessions(user.id)

        if "department_id" in changes:
            department_id = changes["department_id"]
            if department_id is not None:
                department = await self.session.get(LabDepartment, department_id)
                if department is None or department.deleted_at is not None:
                    raise ValidationFailedError(
                        message_ar="القسم غير موجود",
                        message_en="Department not found",
                        field="department_id",
                    )
                principal.assert_department(department_id)
            user.department_id = department_id

        for field in ("email", "full_name_ar", "full_name_en"):
            value = changes.get(field)
            if value is not None:
                setattr(user, field, str(value).strip())

        after = {"roles": [r.code for r in user.roles], "is_active": user.is_active}
        touched = {k for k, v in changes.items() if v is not None}
        if before == after and touched <= {"roles", "is_active"}:
            raise ValidationFailedError(
                message_ar="لا يوجد أي تغيير لحفظه",
                message_en="Nothing to update",
            )

        action = "USER_DISABLED" if before["is_active"] and not after["is_active"] else "USER_UPDATED"
        await self.audit.record(
            action=action,
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            old_values=before,
            new_values=after,
            reason=reason,
            ip_address=ip,
        )
        return user

    async def reset_password(
        self,
        principal: Principal,
        user_id: uuid.UUID,
        *,
        password: str,
        reason: str,
        ip: str | None,
    ) -> User:
        """Set a new password for someone else and force a change at next login.

        The password is never returned, never logged, and every existing session
        of that user is revoked in the same transaction.
        """
        principal.require("users.manage")
        user = await self._load_user(user_id)
        principal.assert_department(user.department_id)
        if user.id == principal.user_id:
            raise PermissionDeniedError(
                message_ar="استخدم مسار تغيير كلمة المرور الشخصي — لا إعادة تعيين ذاتية",
                message_en="Use the personal change-password flow, not self reset",
                field="user_id",
            )
        # an approver may not reset a peer approver's password (sign-as-cover)
        if role_confers_signoff_of(principal) and _target_holds_signoff(user):
            raise PermissionDeniedError(
                message_ar=(
                    "لا يجوز إعادة تعيين كلمة مرور زميل يحمل صلاحية الاعتماد — "
                    "لأن ذلك يسمح بالدخول بحسابه والتوقيع مكانه"
                ),
                message_en=(
                    "You may not reset the password of a peer holding approval authority: "
                    "that would let you sign under their identity"
                ),
                field="user_id",
            )

        problems = password_strength_errors(password)
        if problems:
            raise ValidationFailedError(details={"password_rules": problems}, field="password")

        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.failed_login_count = 0
        user.locked_until = None
        await self._revoke_sessions(user.id)

        await self.audit.record(
            action="USER_PASSWORD_RESET",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            new_values={"must_change_password": True, "sessions_revoked": True},
            reason=reason,
            ip_address=ip,
        )
        return user

    async def unlock(
        self, principal: Principal, user_id: uuid.UUID, *, reason: str, ip: str | None
    ) -> User:
        principal.require("users.manage")
        user = await self._load_user(user_id)
        principal.assert_department(user.department_id)
        if user.locked_until is None and user.failed_login_count == 0:
            raise ConflictError(
                message_ar="الحساب غير مقفل أصلاً",
                message_en="That account is not locked",
            )
        user.locked_until = None
        user.failed_login_count = 0
        await self.audit.record(
            action="USER_UNLOCKED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            new_values={"failed_login_count": 0, "locked_until": None},
            reason=reason,
            ip_address=ip,
        )
        return user

    async def revoke_sessions(
        self, principal: Principal, user_id: uuid.UUID, *, reason: str, ip: str | None
    ) -> int:
        principal.require("users.manage")
        user = await self._load_user(user_id)
        principal.assert_department(user.department_id)
        count = await self._revoke_sessions(user.id)
        await self.audit.record(
            action="USER_SESSIONS_REVOKED",
            entity_type="user",
            entity_id=user.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=user.department_id,
            new_values={"revoked": count},
            reason=reason,
            ip_address=ip,
        )
        return count

    async def _revoke_sessions(self, user_id: uuid.UUID) -> int:
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
        return len(rows)


def role_confers_signoff_of(principal: Principal) -> bool:
    """True when the actor itself holds approval authority."""
    return bool(principal.permissions & SIGNOFF_PERMISSIONS)


def _target_holds_signoff(target: User) -> bool:
    """True when the account being administered carries approval authority."""
    return any(role_confers_signoff(role.code) for role in target.roles)


def serialise_user(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "full_name_ar": user.full_name_ar,
        "full_name_en": user.full_name_en,
        "department_id": str(user.department_id) if user.department_id else None,
        "roles": sorted(r.code for r in user.roles),
        "role_ranks": sorted(ROLE_RANK.get(r.code, 0) for r in user.roles),
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "is_locked": user.locked_until is not None and user.locked_until > datetime.now(timezone.utc),
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "failed_login_count": user.failed_login_count,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "totp_enabled": user.totp_enabled,
        "created_at": user.created_at.isoformat(),
    }
