"""Jadwal scan otomatis per grup IP (menu Agents → Groups).

Revision ID: 0013_scan_schedule
Revises: 0012_dashboard_widgets_width32
Create Date: 2026-11-22

Idempotent: 0001_initial memakai ``Base.metadata.create_all`` sehingga DB baru
sudah membawa kolom dari models. Pola sama dengan 0005_bridge_fdb.
"""
from alembic import op

revision = "0013_scan_schedule"
down_revision = "0012_dashboard_widgets_width32"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"
INDEX = "ix_rani_inventory_scan_groups_due"

COLUMNS = (
    ("schedule_enabled", "BOOLEAN NOT NULL DEFAULT false"),
    ("schedule_mode", "VARCHAR(16) NOT NULL DEFAULT 'interval'"),
    ("schedule_interval_min", "INTEGER NOT NULL DEFAULT 360"),
    ("schedule_time", "VARCHAR(5)"),
    ("schedule_days", "VARCHAR(20)"),
    ("next_run_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_schedule_at", "TIMESTAMP WITH TIME ZONE"),
)


def upgrade() -> None:
    for name, ddl_type in COLUMNS:
        op.execute(
            f"ALTER TABLE {SCHEMA}.scan_groups "
            f"ADD COLUMN IF NOT EXISTS {name} {ddl_type}"
        )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX} ON {SCHEMA}.scan_groups (next_run_at) "
        "WHERE schedule_enabled AND enabled"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{INDEX}")
    for name, _ in reversed(COLUMNS):
        op.execute(
            f"ALTER TABLE {SCHEMA}.scan_groups DROP COLUMN IF EXISTS {name}"
        )
