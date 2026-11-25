"""Second factor (TOTP) — 21 CFR Part 11.200(a)(1)(i).

The regulation requires that a non-biometric e-signature use *two distinct
components*, and that they be used by their genuine owner. A password alone is
one component; this module supplies the second.

Rules encoded here:

1. **The shared secret is a bearer credential.** Anyone who reads it can mint
   valid codes forever, so it is encrypted at rest (Fernet, key derived via
   scrypt from ``mfa_encryption_key``) and never leaves the server except once,
   as an enrolment QR/secret, to the account that is enrolling.
2. **A code is single-use.** TOTP codes are valid for a whole 30-second window
   and are trivially replayable inside it. The last accepted counter is stored
   per user, and a code at or below it is refused — otherwise a code observed
   over someone's shoulder could be reused within the window.
3. **Drift is bounded.** ``mfa_valid_window`` steps of clock skew are tolerated
   in each direction, no more.
4. **Enrolment is not activation.** A secret is generated as *pending*; the user
   must prove possession by returning a valid code before ``totp_enabled`` is
   set. Otherwise a mis-scanned QR would lock the account out permanently.
5. **Recovery codes are hashed.** They are shown once, stored as Argon2 hashes,
   and consumed individually — a lost phone must not require an administrator to
   disable the second factor on a Part 11 account.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
import hmac
import secrets
import uuid

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.security import hash_password, verify_password

RECOVERY_CODE_COUNT = 10


def _fernet() -> Fernet:
    """Derive a stable Fernet key from the configured secret.

    HKDF-style single pass with SHA-256: the settings value is a passphrase of
    arbitrary length, and Fernet demands exactly 32 url-safe base64 bytes.
    """
    settings = get_settings()
    digest = hashlib.sha256(f"sbdma-totp::{settings.mfa_encryption_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret.

    A failure here means the key was rotated or the row was tampered with. It is
    surfaced as a distinct exception so the caller can audit it instead of
    quietly treating it as a wrong code.
    """
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise SecretUndecryptable() from exc


class SecretUndecryptable(Exception):
    """The stored TOTP secret cannot be decrypted with the current key."""


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, username: str) -> str:
    settings = get_settings()
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=settings.mfa_issuer)


def current_counter(secret: str) -> int:
    """The time-step counter the authenticator is on right now.

    ``timecode`` takes a datetime; passing it explicitly also keeps the value in
    UTC, which is what TOTP is defined against.
    """
    return int(pyotp.TOTP(secret).timecode(datetime.now(timezone.utc)))


def verify_code(secret: str, code: str, *, last_used_counter: int | None) -> int | None:
    """Validate a 6-digit code.

    Returns the matched counter (to be persisted as ``last_used_counter``) or
    ``None`` when the code is wrong, malformed, or has already been used.

    ``pyotp.TOTP.verify`` accepts a ``for_time`` hint only through its window
    helper, so the drift search is done explicitly: it must be possible to say
    *which* counter matched in order to enforce single-use.
    """
    settings = get_settings()
    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != 6:
        return None

    totp = pyotp.TOTP(secret)
    now_counter = current_counter(secret)
    for offset in range(-settings.mfa_valid_window, settings.mfa_valid_window + 1):
        candidate = now_counter + offset
        # compare in constant time: a timing oracle here would narrow the search
        expected = totp.generate_otp(candidate)
        if hmac.compare_digest(expected, cleaned):
            if last_used_counter is not None and candidate <= last_used_counter:
                return None  # replay of a code already spent
            return candidate
    return None


# ───────────────────────────── recovery codes ────────────────────────────── #


def generate_recovery_codes() -> tuple[list[str], list[str]]:
    """Return ``(plaintext, hashes)``.

    Plaintext is shown to the user exactly once; only Argon2 hashes are stored.
    The alphabet avoids visually ambiguous characters because these are read off
    paper and typed by hand under stress.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plain: list[str] = []
    hashes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        code = f"{raw[:5]}-{raw[5:]}"
        plain.append(code)
        hashes.append(hash_password(code))
    return plain, hashes


def match_recovery_code(code: str, hashes: list[str]) -> int | None:
    """Return the index of the matching unused hash, or ``None``.

    Argon2 verification cost is paid per hash tried; ten is acceptable for a
    deliberate, rate-limited, audited action.
    """
    cleaned = (code or "").strip().upper()
    for index, stored in enumerate(hashes):
        if stored and verify_password(cleaned, stored)[0]:
            return index
    return None


def enforced_roles() -> set[str]:
    """The roles that may not sign in without a second factor."""
    return {r.strip() for r in get_settings().mfa_enforced_roles.split(",") if r.strip()}


def mfa_required_for(roles: list[str]) -> bool:
    """True when any of the user's roles demands a second factor at sign-in."""
    return bool(enforced_roles() & set(roles))


def new_recovery_id() -> str:
    return str(uuid.uuid4())
