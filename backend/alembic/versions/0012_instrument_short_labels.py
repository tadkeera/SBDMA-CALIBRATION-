"""Unit labels in the bench's own words: ``HPLC (1)``, not ``HPLC-UV (1)``.

Revision 0011 introduced the circle number and back-filled the display labels from the
register's category, which is the *filing* name (``HPLC-UV``, ``UV-VIS``), not the name the
laboratory uses on the bench and on the tile. A unit called ``HPLC-UV (1)`` in the register
and ``HPLC (1)`` by everybody in the room is a small inconsistency that becomes a real one
the moment two screens disagree in front of an auditor.

This revision normalises only the labels that 0011 generated and nobody has since edited:
the form it wrote is exactly ``<category> (<device_number>)``. A label typed by a human —
``مقياس الطيف الضوئي (3)`` or ``HPLC (2) - bench`` — does not match that shape and is left
untouched. Downgrade restores the same rows to the category form, so the migration is
reversible in both directions.

Revision ID: 0012_instrument_short_labels
Revises: 0011_instrument_labels
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text as sa_text

revision = "0012_instrument_short_labels"
down_revision = "0011_instrument_labels"
branch_labels = None
depends_on = None

# ``split_part(category, '-', 1)`` is the bench name: HPLC-UV -> HPLC, UV-VIS -> UV.
_SHORTEN = """
UPDATE instruments
   SET label_en = split_part(category, '-', 1) || ' (' || device_number || ')',
       label_ar = split_part(category, '-', 1) || ' (' || device_number || ')',
       updated_at = now()
 WHERE device_number IS NOT NULL
   AND category LIKE '%-%'
   AND label_en = category || ' (' || device_number || ')'
"""

_RESTORE = """
UPDATE instruments
   SET label_en = category || ' (' || device_number || ')',
       label_ar = category || ' (' || device_number || ')',
       updated_at = now()
 WHERE device_number IS NOT NULL
   AND category LIKE '%-%'
   AND label_en = split_part(category, '-', 1) || ' (' || device_number || ')'
"""


def upgrade() -> None:
    # ``text()`` is required: the statements contain ``%`` (the LIKE patterns), which a
    # driver-level execute reads as a parameter placeholder.
    op.get_bind().execute(sa_text(_SHORTEN))


def downgrade() -> None:
    op.get_bind().execute(sa_text(_RESTORE))
