"""Governance triggers: audit immutability, locked-result guard, department scoping.

These are the invariants that must survive an application bug or a direct SQL
session (master spec §01.2 and §05). They are deliberately implemented in the
database, not in Python.

Revision ID: 0002_governance
Revises: 0001_initial
"""

from __future__ import annotations

from alembic import op

revision = "0002_governance"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


UPGRADE = r"""
-- ═══════════════════════════════════════════════════════════════════════════
-- 1) audit_logs is append-only (ALCOA+ / 21 CFR Part 11)
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_audit_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'audit_logs is append-only (ALCOA+ / 21 CFR Part 11): % is forbidden', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_logs;
CREATE TRIGGER trg_audit_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION sbdma_audit_immutable();

-- TRUNCATE would otherwise wipe the trail while bypassing row triggers
DROP TRIGGER IF EXISTS trg_audit_no_truncate ON audit_logs;
CREATE TRIGGER trg_audit_no_truncate
    BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION sbdma_audit_immutable();

-- ═══════════════════════════════════════════════════════════════════════════
-- 2) Approved (locked) calibration results are frozen
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_locked_result_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_locked THEN
            RAISE EXCEPTION
                'calibration_test_results % is locked after QA approval and cannot be deleted', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.is_locked THEN
        -- Only an authorised unlock (super admin, audited) may clear the flag,
        -- and even then the scientific payload may not change in the same statement.
        IF NEW.is_locked = FALSE
           AND NEW.raw_inputs_jsonb IS NOT DISTINCT FROM OLD.raw_inputs_jsonb
           AND NEW.calculated_outputs_jsonb IS NOT DISTINCT FROM OLD.calculated_outputs_jsonb
           AND NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'calibration_test_results % is locked after QA approval and cannot be modified', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_locked_result_guard ON calibration_test_results;
CREATE TRIGGER trg_locked_result_guard
    BEFORE UPDATE OR DELETE ON calibration_test_results
    FOR EACH ROW EXECUTE FUNCTION sbdma_locked_result_guard();

-- ═══════════════════════════════════════════════════════════════════════════
-- 3) A locked run cannot be reopened or have its signatures rewritten
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_locked_run_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_locked AND NEW.is_locked = FALSE THEN
        RAISE EXCEPTION 'calibration_run % is locked and cannot be reopened', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.is_locked AND (
           NEW.certificate_hash IS DISTINCT FROM OLD.certificate_hash
        OR NEW.qa_approver_id  IS DISTINCT FROM OLD.qa_approver_id
        OR NEW.overall_status  IS DISTINCT FROM OLD.overall_status
    ) THEN
        RAISE EXCEPTION 'calibration_run % certificate payload is immutable after approval', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_locked_run_guard ON calibration_runs;
CREATE TRIGGER trg_locked_run_guard
    BEFORE UPDATE ON calibration_runs
    FOR EACH ROW EXECUTE FUNCTION sbdma_locked_run_guard();

-- ═══════════════════════════════════════════════════════════════════════════
-- 4) Expiry guard (defence in depth behind the service-layer check)
--    An expired reference item may never be attached to a new run.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_expiry_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    ref_expiry date;
BEGIN
    IF NEW.reference_equipment_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT expiry_date INTO ref_expiry
      FROM reference_equipment WHERE id = NEW.reference_equipment_id;
    IF ref_expiry IS NOT NULL AND ref_expiry < CURRENT_DATE THEN
        RAISE EXCEPTION
            'reference_equipment % expired on % and cannot be used in a calibration run',
            NEW.reference_equipment_id, ref_expiry
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_expiry_guard ON calibration_runs;
CREATE TRIGGER trg_expiry_guard
    BEFORE INSERT OR UPDATE OF reference_equipment_id ON calibration_runs
    FOR EACH ROW EXECUTE FUNCTION sbdma_expiry_guard();

-- ═══════════════════════════════════════════════════════════════════════════
-- 5) Department isolation helpers (used by the RLS policies)
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_current_department() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.department_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION sbdma_is_supervisor() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT coalesce(NULLIF(current_setting('app.is_supervisor', true), ''), 'false')::boolean;
$$;

CREATE OR REPLACE FUNCTION sbdma_department_visible(target uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT sbdma_is_supervisor() OR target = sbdma_current_department();
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 6) updated_at maintenance (kept in the DB so raw SQL cannot bypass it)
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sbdma_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users','instruments','reference_equipment','reference_standards',
        'calibration_protocols','test_definitions','acceptance_limits',
        'formula_definitions','calibration_runs','calibration_test_results',
        'maintenance_tickets','roles'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_touch_updated_at ON %I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_touch_updated_at BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION sbdma_touch_updated_at()', t);
    END LOOP;
END;
$$;
"""

DOWNGRADE = r"""
DROP TRIGGER IF EXISTS trg_expiry_guard ON calibration_runs;
DROP TRIGGER IF EXISTS trg_locked_run_guard ON calibration_runs;
DROP TRIGGER IF EXISTS trg_locked_result_guard ON calibration_test_results;
DROP TRIGGER IF EXISTS trg_audit_no_truncate ON audit_logs;
DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_logs;
DROP FUNCTION IF EXISTS sbdma_audit_immutable() CASCADE;
DROP FUNCTION IF EXISTS sbdma_locked_result_guard() CASCADE;
DROP FUNCTION IF EXISTS sbdma_locked_run_guard() CASCADE;
DROP FUNCTION IF EXISTS sbdma_expiry_guard() CASCADE;
DROP FUNCTION IF EXISTS sbdma_current_department() CASCADE;
DROP FUNCTION IF EXISTS sbdma_is_supervisor() CASCADE;
DROP FUNCTION IF EXISTS sbdma_department_visible(uuid) CASCADE;
DROP FUNCTION IF EXISTS sbdma_touch_updated_at() CASCADE;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
