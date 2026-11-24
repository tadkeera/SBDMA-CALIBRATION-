"""ORM models. Importing this package registers all tables on the metadata."""

from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.audit import AuditLog, Notification, SystemSetting
from app.models.base import Base
from app.models.protocol import (
    AcceptanceLimit,
    CalibrationProtocol,
    FormulaDefinition,
    TestDefinition,
)
from app.models.rbac import (
    LabDepartment,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.runs import (
    CalibrationAttachment,
    CalibrationRun,
    CalibrationTestResult,
    MaintenanceTicket,
)

__all__ = [
    "Base",
    "LabDepartment",
    "Permission",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "RefreshSession",
    "Instrument",
    "ReferenceEquipment",
    "ReferenceStandard",
    "CalibrationProtocol",
    "TestDefinition",
    "AcceptanceLimit",
    "FormulaDefinition",
    "CalibrationRun",
    "CalibrationTestResult",
    "CalibrationAttachment",
    "MaintenanceTicket",
    "AuditLog",
    "Notification",
    "SystemSetting",
]
