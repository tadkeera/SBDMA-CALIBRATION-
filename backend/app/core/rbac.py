"""RBAC policy layer — the single place where permission decisions are made.

Deny-by-default. A caller must present both the permission *and*, for
department-scoped resources, a matching department or supervisor status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from app.core.exceptions import PermissionDeniedError

# Canonical permission catalogue (mirrors src/core/types.ts on the frontend)
PERMISSIONS: Final[tuple[str, ...]] = (
    "instruments.view",
    "instruments.create",
    "instruments.update",
    "instruments.delete",
    "calibration.run",
    "calibration.review",
    "calibration.approve",
    "limits.manage",
    "limits.approve",
    "formulas.manage",
    "reports.export",
    "audit.view",
    "settings.manage",
    "users.manage",
    "maintenance.manage",
    "attachments.manage",
)

ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "SUPER_ADMIN": PERMISSIONS,
    "SYSTEM_ADMIN": (
        "instruments.view",
        "instruments.create",
        "instruments.update",
        "instruments.delete",
        "limits.manage",
        "formulas.manage",
        "reports.export",
        "audit.view",
        "settings.manage",
        "users.manage",
        "maintenance.manage",
        "attachments.manage",
    ),
    "ANALYST": ("instruments.view", "calibration.run", "reports.export", "attachments.manage"),
    "TECHNICAL_REVIEWER": (
        "instruments.view",
        "calibration.run",
        "calibration.review",
        "reports.export",
    ),
    "QA_APPROVER": (
        "instruments.view",
        "calibration.review",
        "calibration.approve",
        "limits.approve",
        "limits.manage",
        "reports.export",
        "audit.view",
    ),
    "ENGINEERING_SERVICE": (
        "instruments.view",
        "maintenance.manage",
        "reports.export",
        "attachments.manage",
    ),
    "VIEWER": ("instruments.view",),
}

SUPERVISOR_ROLES: Final[frozenset[str]] = frozenset({"SUPER_ADMIN", "QA_APPROVER", "SYSTEM_ADMIN"})
ROLE_RANK: Final[dict[str, int]] = {
    "VIEWER": 0,
    "ENGINEERING_SERVICE": 1,
    "ANALYST": 2,
    "TECHNICAL_REVIEWER": 3,
    "QA_APPROVER": 4,
    "SYSTEM_ADMIN": 5,
    "SUPER_ADMIN": 6,
}


@dataclass(slots=True)
class Principal:
    """The authenticated actor, resolved from a verified JWT."""

    user_id: UUID
    username: str
    roles: list[str]
    department_id: UUID | None
    permissions: set[str] = field(default_factory=set)
    session_id: str | None = None
    #: True while the account still uses an administrator-issued password. Such a
    #: principal may read its own identity and change the password, nothing else.
    must_change_password: bool = False

    @classmethod
    def build(
        cls,
        *,
        user_id: UUID,
        username: str,
        roles: list[str],
        department_id: UUID | None,
        session_id: str | None = None,
        must_change_password: bool = False,
    ) -> "Principal":
        perms: set[str] = set()
        for role in roles:
            perms.update(ROLE_PERMISSIONS.get(role, ()))
        return cls(
            user_id=user_id,
            username=username,
            roles=roles,
            department_id=department_id,
            permissions=perms,
            session_id=session_id,
            must_change_password=must_change_password,
        )

    # --- capability checks -------------------------------------------------
    @property
    def primary_role(self) -> str:
        return max(self.roles, key=lambda r: ROLE_RANK.get(r, 0)) if self.roles else "VIEWER"

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(
                field=permission,
                details={"required": permission, "role": self.primary_role},
            )

    def is_supervisor(self) -> bool:
        return bool(set(self.roles) & SUPERVISOR_ROLES)

    # --- department isolation (IDOR protection) ----------------------------
    def assert_department(self, target_department_id: UUID | None) -> None:
        """Not-found semantics: an out-of-scope id must never reveal existence."""
        if target_department_id is None:
            return
        if self.is_supervisor():
            return
        if self.department_id != target_department_id:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(
                message_ar="العنصر غير موجود أو خارج نطاق صلاحيتك",
                message_en="Resource not found or outside your scope",
            )

    def assert_can_grant(self, permission: str) -> None:
        """No user may grant a permission they do not hold (privilege escalation)."""
        if not self.has(permission):
            raise PermissionDeniedError(
                message_ar="لا يجوز منح صلاحية لا تملكها",
                message_en="You may not grant a permission you do not hold",
                field=permission,
            )

    def assert_role_assignable(self, role_code: str) -> None:
        my_rank = ROLE_RANK.get(self.primary_role, 0)
        if ROLE_RANK.get(role_code, 99) > my_rank:
            raise PermissionDeniedError(
                message_ar="لا يجوز إسناد دور أعلى من دورك",
                message_en="You may not assign a role above your own",
                field="role",
            )


def assert_segregation_of_duties(
    *, analyst_id: UUID, reviewer_id: UUID | None, qa_approver_id: UUID | None
) -> None:
    """21 CFR Part 11 — three distinct actors for one run."""
    from app.core.exceptions import SegregationOfDutiesError

    if reviewer_id is not None and reviewer_id == analyst_id:
        raise SegregationOfDutiesError(
            message_ar="فصل المهام: المراجع الفني لا يجوز أن يكون محلل التشغيل نفسه",
            message_en="Segregation of duties: the reviewer cannot be the executing analyst",
        )
    if qa_approver_id is not None and qa_approver_id == analyst_id:
        raise SegregationOfDutiesError(
            message_ar="فصل المهام: معتمد ضمان الجودة لا يجوز أن يكون محلل التشغيل نفسه",
            message_en="Segregation of duties: the QA approver cannot be the executing analyst",
        )
    if qa_approver_id is not None and reviewer_id is not None and qa_approver_id == reviewer_id:
        raise SegregationOfDutiesError(
            message_ar="فصل المهام: معتمد ضمان الجودة لا يجوز أن يكون المراجع الفني نفسه",
            message_en="Segregation of duties: the QA approver cannot be the technical reviewer",
        )
