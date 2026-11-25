"""Request bodies for user administration.

Every mutation carries a mandatory ``reason``: an account change without a
documented justification is not acceptable in a validated system, and the string
is written verbatim into the audit chain.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class _ReasonedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 8:
            raise ValueError("سبب الإجراء مطلوب ولا يقل عن 8 أحرف")
        return cleaned


class UpdateUserRequest(_ReasonedRequest):
    roles: list[str] | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None
    email: EmailStr | None = None
    full_name_ar: str | None = Field(default=None, min_length=3, max_length=190)
    full_name_en: str | None = Field(default=None, min_length=3, max_length=190)


class ResetPasswordRequest(_ReasonedRequest):
    # strength is enforced by security.password_strength_errors so the client gets
    # every failed rule at once rather than only the first
    new_password: str = Field(min_length=1, max_length=256)


class UnlockUserRequest(_ReasonedRequest):
    pass


class RevokeSessionsRequest(_ReasonedRequest):
    pass


class UserActionRequest(_ReasonedRequest):
    """Shared shape for the simple one-action endpoints."""
