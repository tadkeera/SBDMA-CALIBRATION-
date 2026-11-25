"""Instrument evidence attachments: owner column, justification, immutability.

Revision ID: 0003_attachments
Revises: 0002_governance

The attachment table existed since 0001 but had no instrument link, no audit
justification and — more importantly — no protection. Filed evidence that can be
silently deleted is not evidence, so the append-only rule lives in PostgreSQL
next to the audit-trail guards (ALCOA+ / 21 CFR Part 11).
"""

from __future__ import annotations

from alembic import op

revision = "0003_attachments"
down_revision = "0002_governance"
branch_labels = None
depends_on = None


UPGRADE = r"""
-- ═══════════════════════════════════════════════════════════════════════════
-- 1) Columns: an attachment must belong to an instrument, and every filing
--    carries the reason it was filed (ALCOA+ attributability).
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE calibration_attachments
    ADD COLUMN IF NOT EXISTS instrument_id UUID
        REFERENCES instruments (id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS description_ar TEXT,
    ADD COLUMN IF NOT EXISTS supersedes_id UUID
        REFERENCES calibration_attachments (id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS ix_calibration_attachments_instrument_id
    ON calibration_attachments (instrument_id);

ALTER TABLE calibration_attachments
    DROP CONSTRAINT IF EXISTS attachment_size_positive;
ALTER TABLE calibration_attachments
    ADD CONSTRAINT attachment_size_positive CHECK (size_bytes > 0);

ALTER TABLE calibration_attachments
    DROP CONSTRAINT IF EXISTS attachment_has_owner;
ALTER TABLE calibration_attachments
    ADD CONSTRAINT attachment_has_owner CHECK (
        instrument_id IS NOT NULL OR run_id IS NOT NULL OR test_result_id IS NOT NULL
    );

-- the checksum is the identity of the content: no two rows may claim the same file
CREATE UNIQUE INDEX IF NOT EXISTS uq_calibration_attachments_sha256
    ON calibration_attachments (sha256_checksum);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2) Append-only: filed evidence cannot be rewritten or deleted, even by SQL
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_attachment_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'calibration_attachments is append-only (ALCOA+): % is forbidden, file a superseding attachment instead',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_attachment_immutable ON calibration_attachments;
CREATE TRIGGER trg_attachment_immutable
    BEFORE UPDATE OR DELETE ON calibration_attachments
    FOR EACH ROW EXECUTE FUNCTION sbdma_attachment_immutable();

-- TRUNCATE bypasses row triggers, so it gets its own guard
CREATE OR REPLACE FUNCTION sbdma_attachment_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE on calibration_attachments is forbidden (ALCOA+)'
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_attachment_no_truncate ON calibration_attachments;
CREATE TRIGGER trg_attachment_no_truncate
    BEFORE TRUNCATE ON calibration_attachments
    FOR EACH STATEMENT EXECUTE FUNCTION sbdma_attachment_no_truncate();
"""

DOWNGRADE = r"""
DROP TRIGGER IF EXISTS trg_attachment_no_truncate ON calibration_attachments;
DROP TRIGGER IF EXISTS trg_attachment_immutable ON calibration_attachments;
DROP FUNCTION IF EXISTS sbdma_attachment_no_truncate() CASCADE;
DROP FUNCTION IF EXISTS sbdma_attachment_immutable() CASCADE;

DROP INDEX IF EXISTS uq_calibration_attachments_sha256;
DROP INDEX IF EXISTS ix_calibration_attachments_instrument_id;

ALTER TABLE calibration_attachments
    DROP CONSTRAINT IF EXISTS attachment_has_owner;
ALTER TABLE calibration_attachments
    DROP CONSTRAINT IF EXISTS attachment_size_positive;

ALTER TABLE calibration_attachments
    DROP COLUMN IF EXISTS supersedes_id,
    DROP COLUMN IF EXISTS description_ar,
    DROP COLUMN IF EXISTS instrument_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
