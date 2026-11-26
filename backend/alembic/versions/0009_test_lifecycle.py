"""test lifecycle + reference manual columns

Two documentary columns on ``test_definitions``, both of them additive and both of them
safe to apply to a live database that is already serving traffic:

``is_active``
    The Control Center switch that takes a test out of routine use (a broken oven sensor,
    a detector sent for repair) without deleting its history. It is added with
    ``server_default true`` so the twenty tests already seeded in production come out of
    the migration enabled — the behaviour of an existing deployment does not change until
    somebody deliberately flips a switch. The index makes the "which tests are enabled"
    filter, used on every protocol read, a single index scan.

``reference_jsonb``
    The Reference Manual entry for a test: overview, ideal readings, evaluation notes and
    scientific sources. It is JSONB because it is a document that is rendered, not
    queried, and it deliberately sits beside the measurement columns rather than among
    them: nothing in this column can influence a verdict.

Neither column rewrites a row, so the migration is instant on a table of this size and
needs no data migration step. ``downgrade`` drops them, which loses documentation only —
no run, limit or formula is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_test_lifecycle"
down_revision = "0008_stored_blobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_definitions",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "test_definitions",
        sa.Column("reference_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_test_definitions_is_active", "test_definitions", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_test_definitions_is_active", table_name="test_definitions")
    op.drop_column("test_definitions", "reference_jsonb")
    op.drop_column("test_definitions", "is_active")
