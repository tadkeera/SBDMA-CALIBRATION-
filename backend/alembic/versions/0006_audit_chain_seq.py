"""audit chain position — makes concurrent appends safe

Two problems, one column:

1. **Fork.** ``AuditService.record`` read the head hash and then inserted, with
   nothing serialising the two steps. Two writers that read the same head both
   chained onto it and the chain forked into two branches — each branch verifies
   alone, the register verifies as broken, and the audit trail has been corrupted
   silently because both writers saw success. It is reachable with two concurrent
   requests today and guaranteed once a Celery worker appends.

   The application fix is an ``pg_advisory_xact_lock`` held for the rest of the
   transaction. This migration adds the column the lock protects: a monotonic
   ``chain_seq`` so the position in the chain is recorded rather than inferred.

2. **Ordering.** ``verify_chain`` ordered rows by ``at`` (microsecond) and then by
   ``id``, a random UUID. Rows sharing a timestamp were replayed in an order the
   chain was never built in, and the verifier reported honest entries as a break.

Existing rows are backfilled in the order the old verifier used, which is also the
order in which they were written under the single-writer assumption. ``chain_seq``
starts at 1 so that ``0`` is not a valid position; NULL means "predates this
migration" and only ever appears if the backfill is interrupted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_audit_chain_seq"
down_revision = "0005_deviations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("chain_seq", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_audit_logs_chain_seq", "audit_logs", ["chain_seq"], unique=True
    )

    # Backfill once, in the order the chain was written. A window function numbers
    # the rows without needing a loop, and the UPDATE is a single statement so the
    # append-only trigger (which guards UPDATE) has to be stood down for it — the
    # trigger guards rows against edits; this is a schema migration adding a
    # column to every row, and the hash does not cover chain_seq, so the chain is
    # unchanged by it.
    op.execute("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_immutable")
    op.execute(
        """
        WITH ordered AS (
            SELECT id, row_number() OVER (ORDER BY at ASC, id ASC) AS seq
            FROM audit_logs
            WHERE chain_seq IS NULL
        )
        UPDATE audit_logs a
        SET chain_seq = ordered.seq
        FROM ordered
        WHERE a.id = ordered.id
        """
    )
    op.execute("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_immutable")


def downgrade() -> None:
    op.drop_index("ix_audit_logs_chain_seq", table_name="audit_logs")
    op.drop_column("audit_logs", "chain_seq")
