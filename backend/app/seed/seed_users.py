"""Seed the initial user set.

Passwords are taken from environment variables when provided; otherwise a
random password is generated and printed once. A hard-coded default password is
never written, and every seeded account is flagged must_change_password.
"""

from __future__ import annotations

import os
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.rbac import LabDepartment, Role, User

SEED_USERS = (
    ("admin", "admin@sbdma.gov.ye", "مدير النظام", "System Administrator", "QA", "SUPER_ADMIN", "SBDMA_ADMIN_PASSWORD"),
    ("qa.manager", "qa.manager@sbdma.gov.ye", "مدير ضمان الجودة", "QA Manager", "QA", "QA_APPROVER", "SBDMA_QA_MANAGER_PASSWORD"),
    ("qa.officer", "qa.officer@sbdma.gov.ye", "مسؤول ضمان الجودة", "QA Officer", "QA", "QA_APPROVER", "SBDMA_QA_OFFICER_PASSWORD"),
    ("supervisor.phys", "supervisor.phys@sbdma.gov.ye", "مشرف مختبر الفيزياء", "Physics Lab Supervisor", "PHYS", "TECHNICAL_REVIEWER", "SBDMA_SUPERVISOR_PASSWORD"),
    ("analyst.phys", "analyst.phys@sbdma.gov.ye", "محلل مختبر الفيزياء", "Physics Lab Analyst", "PHYS", "ANALYST", "SBDMA_ANALYST_PASSWORD"),
    ("analyst.chem", "analyst.chem@sbdma.gov.ye", "محلل مختبر الكيمياء", "Chemistry Lab Analyst", "CHEM", "ANALYST", "SBDMA_ANALYST2_PASSWORD"),
    ("reviewer.phys", "reviewer.phys@sbdma.gov.ye", "المراجع الفني — الفيزياء", "Technical Reviewer — Physics", "PHYS", "TECHNICAL_REVIEWER", "SBDMA_REVIEWER_PASSWORD"),
    ("technician", "technician@sbdma.gov.ye", "فني صيانة", "Maintenance Technician", "PHYS", "ENGINEERING_SERVICE", "SBDMA_TECHNICIAN_PASSWORD"),
    ("viewer", "viewer@sbdma.gov.ye", "مطالع", "Read-only Viewer", "QA", "VIEWER", "SBDMA_VIEWER_PASSWORD"),
)

CREDENTIALS_FILE = os.environ.get("SBDMA_CREDENTIALS_FILE", "/tmp/sbdma-seed-credentials.txt")


async def seed_users(session: AsyncSession) -> dict[str, int]:
    created = {"users": 0}
    generated: list[str] = []

    departments = {
        d.code: d.id for d in (await session.execute(select(LabDepartment))).scalars().all()
    }
    roles = {r.code for r in (await session.execute(select(Role))).scalars().all()}

    for username, email, name_ar, name_en, dept, role_code, env_key in SEED_USERS:
        exists = (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if exists is not None:
            continue
        if role_code not in roles:
            raise RuntimeError(f"role {role_code} must be seeded before users")
        password = os.environ.get(env_key)
        if not password:
            password = secrets.token_urlsafe(18)
            generated.append(f"{username}\t{password}")
        role = await session.get(Role, role_code)
        user = User(
            id=uuid.uuid4(),
            department_id=departments.get(dept),
            username=username,
            email=email,
            full_name_ar=name_ar,
            full_name_en=name_en,
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=True,
        )
        user.roles = [role]
        session.add(user)
        created["users"] += 1

    await session.flush()

    if generated:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as fh:
            fh.write("# SBDMA initial credentials — delete after first sign-in\n")
            fh.write("# username\tpassword\n")
            fh.write("\n".join(generated) + "\n")
        os.chmod(CREDENTIALS_FILE, 0o600)
        created["credentials_file_written"] = 1

    return created
