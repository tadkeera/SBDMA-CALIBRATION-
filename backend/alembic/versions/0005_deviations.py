"""OOS deviations: the investigation record for a failing calibration.

Revision ID: 0005_deviations
Revises: 0004_mfa

Before this, the QA approval path answered a failing run with "raise an OOS
deviation" and no such table existed — the system demanded an action it did not
support. This migration creates the record, protects it, and links it to the run
it investigates.

The append-only rule lives in PostgreSQL rather than only in Python: an
investigation that can be quietly deleted or rewritten is not an investigation,
and the same guarantee already applies to the audit chain and to attachments.
"""

from __future__ import annotations

from alembic import op

revision = "0005_deviations"
down_revision = "0004_mfa"
branch_labels = None
depends_on = None


UPGRADE = r"""
-- ═══════════════════════════════════════════════════════════════════════════
-- 1) The record itself.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS deviations (
    id                     UUID PRIMARY KEY,
    reference              VARCHAR(32)  NOT NULL UNIQUE,
    run_id                 UUID         NOT NULL REFERENCES calibration_runs (id) ON DELETE RESTRICT,
    instrument_id          UUID         NOT NULL REFERENCES instruments (id)      ON DELETE RESTRICT,
    department_id          UUID         REFERENCES lab_departments (id),
    classification         deviation_class  NOT NULL DEFAULT 'MAJOR',
    status                 deviation_status NOT NULL DEFAULT 'OPEN',

    title                  VARCHAR(200) NOT NULL,
    description            TEXT         NOT NULL,

    raised_by              UUID         NOT NULL REFERENCES users (id),
    raised_at              TIMESTAMPTZ  NOT NULL,

    root_cause_category    root_cause_category,
    root_cause             TEXT,
    immediate_action       TEXT,
    investigated_by        UUID         REFERENCES users (id),
    investigated_at        TIMESTAMPTZ,

    capa_action            capa_action,
    capa_notes             TEXT,
    retest_run_id          UUID         REFERENCES calibration_runs (id) ON DELETE RESTRICT,
    closed_by              UUID         REFERENCES users (id),
    closed_at              TIMESTAMPTZ,
    closure_notes          TEXT,

    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_deviations_status     ON deviations (status);
CREATE INDEX IF NOT EXISTS ix_deviations_run        ON deviations (run_id);
CREATE INDEX IF NOT EXISTS ix_deviations_instrument ON deviations (instrument_id);
CREATE INDEX IF NOT EXISTS ix_deviations_department ON deviations (department_id);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2) Integrity: a deviation must describe a failing run, and its phase columns
--    must agree with its status. A CLOSED deviation with no closer is not closed.
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE deviations
    DROP CONSTRAINT IF EXISTS ck_deviations_closed_shape;
ALTER TABLE deviations
    ADD CONSTRAINT ck_deviations_closed_shape CHECK (
        status <> 'CLOSED'
        OR (closed_by IS NOT NULL AND closed_at IS NOT NULL AND capa_action IS NOT NULL)
    );

ALTER TABLE deviations
    DROP CONSTRAINT IF EXISTS ck_deviations_investigated_shape;
ALTER TABLE deviations
    ADD CONSTRAINT ck_deviations_investigated_shape CHECK (
        status NOT IN ('PENDING_VERIFICATION', 'CLOSED')
        OR (investigated_by IS NOT NULL AND investigated_at IS NOT NULL AND root_cause IS NOT NULL)
    );

ALTER TABLE deviations
    DROP CONSTRAINT IF EXISTS ck_deviations_retest_not_self;
ALTER TABLE deviations
    ADD CONSTRAINT ck_deviations_retest_not_self CHECK (retest_run_id IS NULL OR retest_run_id <> run_id);

-- The run a deviation points at must actually have failed or been incomplete.
-- Letting one reference a passing run would create a paper trail that contradicts
-- the data it claims to investigate.
CREATE OR REPLACE FUNCTION trg_deviation_run_must_fail() RETURNS TRIGGER AS $$
DECLARE
    run_status TEXT;
BEGIN
    SELECT overall_status::text INTO run_status FROM calibration_runs WHERE id = NEW.run_id;

    IF run_status IS NULL THEN
        RAISE EXCEPTION 'deviation % references a run that does not exist', NEW.reference;
    END IF;

    IF run_status NOT IN ('FAIL', 'INCOMPLETE') THEN
        RAISE EXCEPTION
            'deviation % must reference a failed or incomplete run (run status: %)',
            NEW.reference, run_status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_deviation_run_must_fail ON deviations;
CREATE TRIGGER trg_deviation_run_must_fail
    BEFORE INSERT OR UPDATE OF run_id ON deviations
    FOR EACH ROW EXECUTE FUNCTION trg_deviation_run_must_fail();

-- ═══════════════════════════════════════════════════════════════════════════
-- 3) Append-only: no deletion, and no rewriting of the investigative record.
--    Status/phase columns stay writable (that is the workflow); the identity of
--    the deviation and what it points at do not.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION trg_deviation_immutable() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'deviations are append-only: % cannot be deleted', OLD.reference;
    END IF;

    IF NEW.reference   <> OLD.reference
       OR NEW.run_id        <> OLD.run_id
       OR NEW.instrument_id <> OLD.instrument_id
       OR NEW.raised_by     <> OLD.raised_by
       OR NEW.raised_at     <> OLD.raised_at
       OR NEW.title         <> OLD.title
       OR NEW.description   <> OLD.description
       OR NEW.classification <> OLD.classification THEN
        RAISE EXCEPTION
            'deviation % : identity, subject and classification are immutable once raised',
            OLD.reference;
    END IF;

    -- a closed deviation is final; corrections require a new deviation
    IF OLD.status IN ('CLOSED', 'CANCELLED') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'deviation % is % and cannot change status', OLD.reference, OLD.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_deviation_immutable ON deviations;
CREATE TRIGGER trg_deviation_immutable
    BEFORE UPDATE OR DELETE ON deviations
    FOR EACH ROW EXECUTE FUNCTION trg_deviation_immutable();

CREATE OR REPLACE FUNCTION trg_deviation_no_truncate() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE is not permitted on deviations';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_deviation_no_truncate ON deviations;
CREATE TRIGGER trg_deviation_no_truncate
    BEFORE TRUNCATE ON deviations
    FOR EACH STATEMENT EXECUTE FUNCTION trg_deviation_no_truncate();
"""

DOWNGRADE = r"""
DROP TRIGGER IF EXISTS trg_deviation_no_truncate ON deviations;
DROP TRIGGER IF EXISTS trg_deviation_immutable ON deviations;
DROP TRIGGER IF EXISTS trg_deviation_run_must_fail ON deviations;
DROP FUNCTION IF EXISTS trg_deviation_no_truncate();
DROP FUNCTION IF EXISTS trg_deviation_immutable();
DROP FUNCTION IF EXISTS trg_deviation_run_must_fail();
DROP TABLE IF EXISTS deviations;
DROP TYPE IF EXISTS deviation_status;
DROP TYPE IF EXISTS deviation_class;
DROP TYPE IF EXISTS root_cause_category;
DROP TYPE IF EXISTS capa_action;
"""


def upgrade() -> None:
    # the enum types must exist before the table that uses them
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE deviation_status AS ENUM ('OPEN','INVESTIGATING','PENDING_VERIFICATION','CLOSED','CANCELLED'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE deviation_class AS ENUM ('CRITICAL','MAJOR','MINOR'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE root_cause_category AS ENUM "
        "('INSTRUMENT_FAULT','METHOD_ERROR','OPERATOR_ERROR','MATERIAL_STANDARD',"
        "'ENVIRONMENTAL','SOFTWARE','NO_CAUSE_FOUND','NOT_INVESTIGATED'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE capa_action AS ENUM "
        "('INSTRUMENT_RESTORED','RECALIBRATION_PERFORMED','METHOD_REVISED',"
        "'RETRAINING_REQUIRED','INSTRUMENT_RETIRED','NO_ACTION_REQUIRED'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
