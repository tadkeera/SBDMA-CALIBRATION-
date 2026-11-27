"""instrument display labels and the circle number

The laboratory asked for its equipment to be presented as units: **HPLC (1)**,
**HPLC (2)**, each unit a tile on the laboratory screen, each tile holding the same
twenty tests. Three things therefore have to be stored on the instrument row rather
than derived at render time:

``label_ar`` / ``label_en``
    the name the laboratory calls the unit ("HPLC (1)"), in both languages;
``device_number``
    the number in the circle. It is assigned once, when the unit is registered, and
    is never recomputed from ``COUNT(*)`` — deleting a unit must not renumber the
    units still in service, and a certificate printed last year must still match the
    tile on the screen today.

Existing rows are numbered deterministically: by ``asset_code`` within the
department, which for the seeded register gives the single unit already in place
``device_number = 1`` and the label "HPLC (1)". Nothing is dropped, nothing is
rewritten beyond the three new columns, and ``downgrade()`` removes exactly what
this migration added.

The tests themselves are **not** copied into a new table. An instrument is already
fathered by the approved protocol of its category (``calibration_protocols`` →
``test_definitions``), so a second unit of the same category is entitled to the same
twenty tests by construction. Copying the definitions per unit would fork the
protocol: a limit approved once for the laboratory would have to be approved again
for every unit added afterwards, and the two copies would drift. What a unit *does*
own is its own runs and its own certificates, which already carry ``instrument_id``.
"""

from __future__ import annotations

from alembic import op

revision = "0011_instrument_labels"
down_revision = "0010_supervisor_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.exec_driver_sql("ALTER TABLE instruments ADD COLUMN IF NOT EXISTS label_ar VARCHAR(80)")
    bind.exec_driver_sql("ALTER TABLE instruments ADD COLUMN IF NOT EXISTS label_en VARCHAR(80)")
    bind.exec_driver_sql("ALTER TABLE instruments ADD COLUMN IF NOT EXISTS device_number INTEGER")

    # Number the units that are already registered: per department, by asset code.
    # Rows that were soft-deleted keep their number so a restore cannot collide.
    bind.exec_driver_sql(
        """
        WITH numbered AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY asset_code) AS seq
            FROM instruments
        )
        UPDATE instruments AS i
           SET device_number = numbered.seq
          FROM numbered
         WHERE i.id = numbered.id
           AND i.device_number IS NULL
        """
    )

    # "HPLC (n)" for the units that carry a number and no label yet. The category is
    # used as the stem because that is what the laboratory calls the equipment.
    bind.exec_driver_sql(
        """
        UPDATE instruments
           SET label_en = COALESCE(label_en, category || ' (' || device_number || ')'),
               label_ar = COALESCE(label_ar, category || ' (' || device_number || ')')
         WHERE device_number IS NOT NULL
        """
    )

    bind.exec_driver_sql(
        "ALTER TABLE instruments ADD CONSTRAINT ck_instruments_device_number_positive "
        "CHECK (device_number IS NULL OR device_number > 0)"
    )
    bind.exec_driver_sql(
        "ALTER TABLE instruments ADD CONSTRAINT uq_instrument_dept_number "
        "UNIQUE (department_id, device_number)"
    )
    bind.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_instruments_device_number ON instruments (device_number)")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("DROP INDEX IF EXISTS ix_instruments_device_number")
    bind.exec_driver_sql("ALTER TABLE instruments DROP CONSTRAINT IF EXISTS uq_instrument_dept_number")
    bind.exec_driver_sql("ALTER TABLE instruments DROP CONSTRAINT IF EXISTS ck_instruments_device_number_positive")
    bind.exec_driver_sql("ALTER TABLE instruments DROP COLUMN IF EXISTS device_number")
    bind.exec_driver_sql("ALTER TABLE instruments DROP COLUMN IF EXISTS label_en")
    bind.exec_driver_sql("ALTER TABLE instruments DROP COLUMN IF EXISTS label_ar")
