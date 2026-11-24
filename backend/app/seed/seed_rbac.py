"""Seed departments, permissions and roles from the RBAC matrix."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import PERMISSIONS, ROLE_PERMISSIONS, ROLE_RANK
from app.models.rbac import LabDepartment, Permission, Role, RolePermission

DEPARTMENTS = (
    ("CHEM", "قسم الكيمياء", "Chemistry Department", "المبنى الرئيسي — الدور الثاني"),
    ("MICRO", "قسم الأحياء الدقيقة", "Microbiology Department", "المبنى الرئيسي — الدور الثالث"),
    ("PHYS", "قسم الفيزياء والتحليل الطيفي", "Physics & Spectroscopy", "مبنى المختبرات — الدور الأول"),
    ("PHARMA", "قسم الصيدلانيات", "Pharmaceutics Department", "المبنى الرئيسي — الدور الأول"),
    ("QA", "وحدة ضمان الجودة", "Quality Assurance Unit", "مبنى الإدارة — الدور الرابع"),
)

ROLE_META = {
    "SUPER_ADMIN": ("المدير الأعلى للنظام", "Super Administrator"),
    "SYSTEM_ADMIN": ("مدير النظام", "System Administrator"),
    "QA_APPROVER": ("معتمد ضمان الجودة", "QA Approver"),
    "TECHNICAL_REVIEWER": ("المراجع الفني", "Technical Reviewer"),
    "ANALYST": ("محلل مختبر", "Laboratory Analyst"),
    "ENGINEERING_SERVICE": ("خدمات هندسية وصيانة", "Engineering Service"),
    "VIEWER": ("مطالع", "Read-only Viewer"),
}

PERMISSION_META: dict[str, tuple[str, str, str]] = {
    "instruments.view": ("عرض الأجهزة", "View instruments", "instruments"),
    "instruments.create": ("إضافة جهاز", "Create instrument", "instruments"),
    "instruments.update": ("تعديل جهاز", "Update instrument", "instruments"),
    "instruments.delete": ("حذف جهاز", "Delete instrument", "instruments"),
    "calibration.run": ("تنفيذ معايرة", "Execute calibration", "calibration"),
    "calibration.review": ("مراجعة فنية", "Technical review", "calibration"),
    "calibration.approve": ("اعتماد ضمان الجودة", "QA approval", "calibration"),
    "limits.approve": ("اعتماد حدود القبول", "Approve acceptance limits", "governance"),
    "limits.manage": ("إدارة حدود القبول", "Manage acceptance limits", "governance"),
    "formulas.manage": ("إدارة المعادلات", "Manage formula definitions", "governance"),
    "audit.view": ("عرض سجل التدقيق", "View audit trail", "audit"),
    "users.manage": ("إدارة المستخدمين", "Manage users", "admin"),
    "maintenance.manage": ("إدارة الصيانة", "Manage maintenance", "maintenance"),
    "reports.export": ("تصدير التقارير", "Export reports", "reports"),
    "settings.manage": ("إعدادات النظام", "System settings", "admin"),
}


async def seed_rbac(session: AsyncSession) -> dict[str, int]:
    created = {"departments": 0, "permissions": 0, "roles": 0, "role_permissions": 0}

    for code, name_ar, name_en, location in DEPARTMENTS:
        exists = (
            await session.execute(select(LabDepartment).where(LabDepartment.code == code))
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                LabDepartment(
                    id=uuid.uuid4(),
                    code=code,
                    name_ar=name_ar,
                    name_en=name_en,
                    location=location,
                    is_active=True,
                )
            )
            created["departments"] += 1
    await session.flush()

    for key in sorted(PERMISSIONS):
        exists = await session.get(Permission, key)
        if exists is None:
            name_ar, name_en, group = PERMISSION_META.get(key, (key, key, "general"))
            session.add(
                Permission(code=key, name_ar=name_ar, name_en=name_en, category=group)
            )
            created["permissions"] += 1
    await session.flush()

    for role_code, (name_ar, name_en) in ROLE_META.items():
        role = await session.get(Role, role_code)
        if role is None:
            session.add(
                Role(
                    code=role_code,
                    name_ar=name_ar,
                    name_en=name_en,
                    is_system=True,
                    rank=ROLE_RANK.get(role_code, 0),
                )
            )
            created["roles"] += 1
    await session.flush()

    existing_links = {
        (rp.role_code, rp.permission_code)
        for rp in (await session.execute(select(RolePermission))).scalars().all()
    }
    for role_code, perms in ROLE_PERMISSIONS.items():
        for perm in perms:
            if (role_code, perm) not in existing_links:
                session.add(RolePermission(role_code=role_code, permission_code=perm))
                created["role_permissions"] += 1

    await session.flush()
    return created
