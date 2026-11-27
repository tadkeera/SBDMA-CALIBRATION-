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
    # Enabling/disabling a test in the field is a governance decision, not an editing
    # one: it changes what the laboratory is allowed to execute, so it is separated
    # from limits.manage and audited on its own.
    "tests.manage_status",
    "reports.export",
    "audit.view",
    "settings.manage",
    "users.manage",
    "maintenance.manage",
    "attachments.manage",
    # OOS deviations: raising one is separated from closing one, so the person who
    # investigates cannot also pronounce their own investigation complete.
    "deviations.raise",
    "deviations.investigate",
    "deviations.close",
    # Granting approval authority is a governance act in its own right, so it is a
    # permission instead of something implied by users.manage. Since release 2.4.0 the
    # super administrator *and* the administrator of accounts both hold it (the laboratory
    # asked for that explicitly), and QA holds it so a second approver can be appointed
    # during an absence. What remains forbidden is stated positively elsewhere: nobody may
    # grant a permission they do not hold (assert_can_grant), and nobody may sign a run they
    # executed (segregation of duties, checked on every approval and by the database).
    "authority.grant",
)

#: Permissions that constitute an electronic signature on a measurement. Granting any of
#: them to another account is itself an audited governance decision, and is checked
#: against ``authority.grant`` (the requester) and ``assert_can_grant`` (where the
#: requester legitimately holds it — QA may appoint a second QA officer).
SIGNOFF_PERMISSIONS: frozenset[str] = frozenset(
    {"calibration.approve", "limits.approve", "authority.grant"}
)

#: Roles whose responsibility is *approval or administration*, not measurement. A member
#: of these roles is not counted as an operator of the laboratory, and the per-unit
#: laboratory screen is hidden from them: QA reads results for approval on the approval
#: screen, it does not enter readings on the bench.
OPERATOR_ROLES: frozenset[str] = frozenset({"ANALYST", "SUPERVISOR"})

ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "SUPER_ADMIN": PERMISSIONS,
    "SYSTEM_ADMIN": (
        "instruments.view",
        "instruments.create",
        "instruments.update",
        "instruments.delete",
        "limits.manage",
        "formulas.manage",
        "tests.manage_status",
        "reports.export",
        "audit.view",
        "settings.manage",
        "users.manage",
        "maintenance.manage",
        "attachments.manage",
        # The approval office reads results, raises deviations against what it found and
        # investigates them. An administrator that may appoint an approver must hold the
        # same, or the appointment it is trusted to make would require permissions its own
        # role cannot confer. None of these is a signature: reading a result, raising a
        # deviation and investigating it are what quality staff do before they decide.
        # ``audit.view`` is already held by this role.
        "calibration.review",
        "deviations.raise",
        "deviations.investigate",
        "deviations.close",
        # Release 2.4.0: the laboratory's rule is that an administrator may give the QA
        # signature to a second officer, so this office holds the grant. It still holds no
        # signature of its own (no calibration.approve / limits.approve), and it can never
        # sign a run: approval authority is a run-level fact about a person, not a role.
        "authority.grant",
    ),
    "ANALYST": (
        "instruments.view",
        "calibration.run",
        "reports.export",
        "attachments.manage",
        "deviations.raise",
    ),
    "SUPERVISOR": (
        "instruments.view",
        "calibration.run",
        "calibration.review",
        "reports.export",
    ),
    "QA_APPROVER": (
        "instruments.view",
        "calibration.review",
        "calibration.approve",
        # QA is the office that can appoint a second approver: that is how a laboratory
        # with one QA manager survives an absence without the administrator minting
        # signatures it does not hold.
        "authority.grant",
        "limits.approve",
        "limits.manage",
        "reports.export",
        "audit.view",
        "deviations.raise",
        "deviations.investigate",
        "deviations.close",
    ),
    "ENGINEERING_SERVICE": (
        "instruments.view",
        "maintenance.manage",
        "reports.export",
        "attachments.manage",
        # a maintenance-induced failure is raised by whoever fixes the instrument
        "deviations.raise",
    ),
    "VIEWER": ("instruments.view",),
}

SUPERVISOR_ROLES: Final[frozenset[str]] = frozenset({"SUPER_ADMIN", "QA_APPROVER", "SYSTEM_ADMIN"})
#: Ranks are about *authority over people*, and the two administrative offices share the
#: top of it. Release 2.4.0 changed the rule that a super administrator is the only office
#: able to award an electronic signature: a system administrator that the laboratory has
#: trusted with accounts and equipment may also award approval authority. What still keeps
#: this safe is not the rank but two sharper rules — nobody may grant a permission they do
#: not hold themselves (``assert_can_grant``), and nobody may sign a run they executed
#: (segregation of duties, enforced at the run level and in the database). The approver
#: therefore sits below both administrative offices: QA signs measurements, it does not
#: administer accounts.
ROLE_RANK: Final[dict[str, int]] = {
    "VIEWER": 0,
    "ENGINEERING_SERVICE": 1,
    "ANALYST": 2,
    "SUPERVISOR": 3,
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
    #: True when the role mandates a second factor but the account has not
    #: enrolled. Such a principal may only reach the enrolment routes.
    mfa_enrolment_required: bool = False

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
        mfa_enrolment_required: bool = False,
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
            mfa_enrolment_required=mfa_enrolment_required,
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

    @property
    def is_operator(self) -> bool:
        """True when this actor is a bench operator of the laboratory.

        The per-unit laboratory screen is reached through this property, not through
        ``calibration.run`` alone: QA and the administrators also hold that permission
        (the super administrator holds all of them), but they do not enter readings on a
        unit and must not see the laboratory gallery. A multi-role account that holds
        ANALYST or SUPERVISOR *alongside* QA stays an operator — the capability is
        additive, and the screen is one the person legitimately works on.
        """
        return bool(set(self.roles) & OPERATOR_ROLES)

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
            message_ar="فصل المهام: مشرف المختبر لا يجوز أن يكون محلل التشغيل نفسه",
            message_en="Segregation of duties: the reviewer cannot be the executing analyst",
        )
    if qa_approver_id is not None and qa_approver_id == analyst_id:
        raise SegregationOfDutiesError(
            message_ar="فصل المهام: معتمد ضمان الجودة لا يجوز أن يكون محلل التشغيل نفسه",
            message_en="Segregation of duties: the QA approver cannot be the executing analyst",
        )
    if qa_approver_id is not None and reviewer_id is not None and qa_approver_id == reviewer_id:
        raise SegregationOfDutiesError(
            message_ar="فصل المهام: معتمد ضمان الجودة لا يجوز أن يكون مشرف المختبر نفسه",
            message_en="Segregation of duties: the QA approver cannot be the technical reviewer",
        )
