from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=8)

    @field_validator("username")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.strip().lower()


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class RoleOut(ORMModel):
    code: str
    name_ar: str
    name_en: str


class MeOut(ORMModel):
    id: uuid.UUID
    username: str
    email: str
    full_name_ar: str
    full_name_en: str
    department_id: uuid.UUID | None
    department_code: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    is_active: bool
    totp_enabled: bool = False
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    # strength is enforced by security.password_strength_errors so the client
    # receives every failing rule, not a bare length error
    new_password: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=8, max_length=500)


class SignaturePayload(BaseModel):
    """21 CFR Part 11 electronic signature."""

    password: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 8:
            raise ValueError("سبب التوقيع مطلوب ولا يقل عن 8 أحرف")
        return cleaned


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    full_name_ar: str = Field(min_length=3, max_length=190)
    full_name_en: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=12, max_length=256)
    department_id: uuid.UUID | None = None
    roles: list[str] = Field(min_length=1)
