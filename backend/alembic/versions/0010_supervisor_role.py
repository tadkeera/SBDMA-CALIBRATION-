"""role rename: TECHNICAL_REVIEWER → SUPERVISOR

The laboratory asked for the second-tier role to be called **Supervisor** — the person who
technically reviews a calibration — instead of "Technical Reviewer". The role code is a
primary key, referenced by ``user_roles`` and ``role_permissions``, so it cannot simply be
renamed in place while those rows point at it.

The safe sequence, in one transaction:
  1. insert the ``SUPERVISOR`` row, copying the Arabic name, rank and system flag,
  2. copy every permission the old role carried,
  3. copy every user assignment,
  4. delete the old links and the old role row.

Nothing is dropped before its replacement exists, so an interrupted migration leaves the
database exactly as it was (Alembic runs each migration in a single transaction on
PostgreSQL). Existing assignments are preserved: a user who could review before the
migration can review after it, with the same permissions and the same rank.

``downgrade`` performs the mirror operation, so the rename is reversible.
"""

from __future__ import annotations

from alembic import op

revision = "0010_supervisor_role"
down_revision = "0009_test_lifecycle"
branch_labels = None
depends_on = None

OLD = "TECHNICAL_REVIEWER"
NEW = "SUPERVISOR"


def _rename(old: str, new: str, name_en: str) -> None:
    bind = op.get_bind()
    # 1 + 2: the replacement role and its permissions, copied from the old row
    bind.exec_driver_sql(
        f"""
        INSERT INTO roles (code, name_ar, name_en, is_system, rank, created_at)
        SELECT '{new}', name_ar, '{name_en}', is_system, rank, now()
        FROM roles WHERE code = '{old}'
        ON CONFLICT (code) DO NOTHING
        """
    )
    bind.exec_driver_sql(
        f"""
        INSERT INTO role_permissions (role_code, permission_code)
        SELECT '{new}', permission_code FROM role_permissions WHERE role_code = '{old}'
        ON CONFLICT DO NOTHING
        """
    )
    # 3 + 4: move the assignments, then retire the old role
    bind.exec_driver_sql(
        f"""
        INSERT INTO user_roles (user_id, role_code)
        SELECT user_id, '{new}' FROM user_roles WHERE role_code = '{old}'
        ON CONFLICT DO NOTHING
        """
    )
    bind.exec_driver_sql(f"DELETE FROM user_roles WHERE role_code = '{old}'")
    bind.exec_driver_sql(f"DELETE FROM role_permissions WHERE role_code = '{old}'")
    bind.exec_driver_sql(f"DELETE FROM roles WHERE code = '{old}'")


def upgrade() -> None:
    _rename(OLD, NEW, "Supervisor")


def downgrade() -> None:
    _rename(NEW, OLD, "Technical Reviewer")
