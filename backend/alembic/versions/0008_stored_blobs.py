"""stored_blobs — the durable copy of every filed document

The filesystem is a cache on a serverless platform: ``/tmp`` is per-instance and is
wiped between invocations, while the row that describes an attachment (its path, its
sha256, who filedit and when) survives in Postgres. That mismatch is the one way this
system could end up holding a signed record it cannot produce.

So the bytes get a home in the database too. ``key`` is the same relative path the file
has on disk, which means an existing deployment needs no data migration: rows are
written on the next upload, and anything older is still served from a real volume.

``body`` is BYTEA, not base64 in JSON: no size inflation, and Postgres stores large
values out of line (TOAST) so a routine ``SELECT`` that does not name the column never
pays for it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_stored_blobs"
down_revision = "0007_notif_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_blobs",
        sa.Column("key", sa.String(length=512), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # "what did this release file, and does it still hash correctly" is asked per
    # content hash, not per path
    op.create_index("ix_stored_blobs_sha256", "stored_blobs", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_stored_blobs_sha256", table_name="stored_blobs")
    op.drop_table("stored_blobs")
