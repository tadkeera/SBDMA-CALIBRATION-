"""Second factor (TOTP): encrypted secret, replay counter, recovery codes.

Revision ID: 0004_mfa
Revises: 0003_attachments

21 CFR Part 11.200(a)(1)(i) requires two distinct identification components for
a non-biometric e-signature. The ``users`` table already carried ``totp_secret``
and ``totp_enabled`` from 0001, but nothing read them and nothing could enforce
single-use of a code. This migration adds what enforcement actually needs:

* ``totp_secret`` is widened (an encrypted value is far longer than a bare
  base32 secret) and documented as ciphertext, never plaintext;
* ``totp_last_counter`` records the highest accepted 30-second step, because a
  TOTP code stays valid for its whole window and would otherwise be replayable;
* ``totp_recovery_hashes`` holds Argon2 hashes of one-time recovery codes so a
  lost phone does not require an administrator to strip the second factor off a
  Part 11 account.
"""

from __future__ import annotations

from alembic import op

revision = "0004_mfa"
down_revision = "0003_attachments"
branch_labels = None
depends_on = None


UPGRADE = r"""
-- ═══════════════════════════════════════════════════════════════════════════
-- 1) The stored secret is ciphertext (Fernet token), not the raw base32 value.
--    A raw TOTP secret is 32 characters; the encrypted form is ~120-180. An
--    existing 64-character column would silently truncate it.
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE users
    ALTER COLUMN totp_secret TYPE VARCHAR(255);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2) Replay protection: remember the last accepted time-step. Without it a code
--    observed once stays usable for the remainder of its 30-second window.
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS totp_last_counter BIGINT,
    ADD COLUMN IF NOT EXISTS totp_enrolled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS totp_recovery_hashes VARCHAR(255)[];

-- ═══════════════════════════════════════════════════════════════════════════
-- 3) An account cannot claim to be enrolled without a secret to verify against.
--    A flag with no secret is a lockout waiting to happen.
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE users
    DROP CONSTRAINT IF EXISTS ck_users_totp_secret_present;
ALTER TABLE users
    ADD CONSTRAINT ck_users_totp_secret_present
    CHECK (NOT totp_enabled OR totp_secret IS NOT NULL);
"""

DOWNGRADE = r"""
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_totp_secret_present;
ALTER TABLE users
    DROP COLUMN IF EXISTS totp_recovery_hashes,
    DROP COLUMN IF EXISTS totp_enrolled_at,
    DROP COLUMN IF EXISTS totp_last_counter;
ALTER TABLE users
    ALTER COLUMN totp_secret TYPE VARCHAR(64);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
