"""notification dedup — one notice per recipient per condition

The due-date job was idempotent when run twice in sequence and duplicated when two
workers ran it at the same time: the check ("has this condition been announced?")
and the insert were two statements with nothing between them. Two Celery workers
processing a retried task is not an edge case — it happened on the first honest
concurrency test.

A uniqueness constraint is the only version of this rule that survives concurrency,
because it is enforced by the storage engine rather than by the code that happens to
be running. The generated column is the ``dedup_key`` the service computes, so the
application and the constraint cannot disagree about what "the same notice" means.

Generated columns require an immutable expression, so the payload's text is keyed by
a stable path rather than by a function of the whole document.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_notif_dedup"
down_revision = "0006_audit_chain_seq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicates would block the constraint. Keep the earliest of each
    # group — it is the one that was actually sent/read — and drop the rest.
    op.execute(
        """
        DELETE FROM notifications n
        USING notifications keep
        WHERE n.payload_jsonb ? 'dedup_key'
          AND keep.payload_jsonb ? 'dedup_key'
          AND n.user_id IS NOT DISTINCT FROM keep.user_id
          AND n.payload_jsonb->>'dedup_key' = keep.payload_jsonb->>'dedup_key'
          AND (keep.created_at, keep.id) < (n.created_at, n.id)
        """
    )
    op.execute(
        """
        ALTER TABLE notifications
        ADD COLUMN dedup_key varchar(255)
        GENERATED ALWAYS AS (payload_jsonb->>'dedup_key') STORED
        """
    )
    op.create_index(
        "uq_notifications_recipient_dedup",
        "notifications",
        ["user_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notifications_recipient_dedup", table_name="notifications")
    op.drop_column("notifications", "dedup_key")
