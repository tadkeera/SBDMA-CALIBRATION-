"""Authentication primitives: Argon2id hashing and JWT access/refresh tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import Settings, get_settings

TokenKind = Literal["access", "refresh"]

# Argon2id per RFC 9106 / OWASP recommendation (master spec §06.2).
_hasher = PasswordHasher()


def _hasher_for(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
        hash_len=32,
        salt_len=16,
    )


def hash_password(password: str) -> str:
    return _hasher_for(get_settings()).hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (valid, updated_hash). A rehash is proposed when parameters changed."""
    try:
        _hasher_for(get_settings()).verify(password_hash, password)
        if _hasher_for(get_settings()).check_needs_rehash(password_hash):
            return True, hash_password(password)
        return True, None
    except (VerifyMismatchError, InvalidHashError):
        return False, None


def password_strength_errors(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < 12:
        problems.append("كلمة المرور يجب أن تكون 12 حرفاً على الأقل")
    if not any(c.islower() for c in password):
        problems.append("يجب أن تحتوي على حرف صغير")
    if not any(c.isupper() for c in password):
        problems.append("يجب أن تحتوي على حرف كبير")
    if not any(c.isdigit() for c in password):
        problems.append("يجب أن تحتوي على رقم")
    if not any(c in "!@#$%^&*()-_=+[]{};:,.?/\\|~`\"'" for c in password):
        problems.append("يجب أن تحتوي على رمز خاص")
    return problems


def create_token(
    subject: str,
    kind: TokenKind,
    *,
    role: str | None = None,
    department_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if kind == "access":
        exp = now + timedelta(minutes=settings.jwt_access_ttl_minutes)
    else:
        exp = now + timedelta(days=settings.jwt_refresh_ttl_days)
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": kind,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid.uuid4()),
        "iss": "sbdma-calibration",
        "aud": "sbdma-ui",
    }
    if role:
        payload["role"] = role
    if department_id:
        payload["dept"] = department_id
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_kind: TokenKind) -> dict[str, Any]:
    """Decode and validate. Raises ValueError on any deviation."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="sbdma-ui",
            issuer="sbdma-calibration",
        )
    except JWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc
    if payload.get("typ") != expected_kind:
        raise ValueError("token type mismatch")
    if not payload.get("sub"):
        raise ValueError("token missing subject")
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def certificate_fingerprint(payload: str) -> str:
    """SHA-256 certificate fingerprint (used for QR verification)."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
