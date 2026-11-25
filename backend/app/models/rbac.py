"""RBAC, departments and users."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeletable, Timestamped, UUIDPrimaryKey


class LabDepartment(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "lab_departments"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str | None] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="department")


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_ar: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)


class Role(Base, Timestamped):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions", lazy="selectin"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_code: Mapped[str] = mapped_column(
        ForeignKey("roles.code", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class User(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "users"

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), index=True
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(190), unique=True, nullable=False)
    full_name_ar: Mapped[str] = mapped_column(String(190), nullable=False)
    full_name_en: Mapped[str] = mapped_column(String(190), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Fernet-encrypted shared secret; a caller who reads it can mint codes forever
    totp_secret: Mapped[str | None] = mapped_column(String(255))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: highest time-step already accepted — TOTP codes are replayable inside their
    #: 30-second window unless this is enforced
    totp_last_counter: Mapped[int | None] = mapped_column(BigInteger)
    totp_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Argon2 hashes of the one-time recovery codes; plaintext is shown once
    totp_recovery_hashes: Mapped[list[str] | None] = mapped_column(ARRAY(String(255)))

    department: Mapped[LabDepartment | None] = relationship(back_populates="users")
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_code", name="uq_user_roles_user_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_code: Mapped[str] = mapped_column(
        ForeignKey("roles.code", ondelete="CASCADE"), primary_key=True
    )


class RefreshSession(Base):
    """Server-side refresh-token registry so sessions can be revoked instantly."""

    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
