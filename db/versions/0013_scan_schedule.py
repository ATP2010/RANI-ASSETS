"""Jadwal scan otomatis per grup IP (menu Agents → Groups).

Revision ID: 0013_scan_schedule
Revises: 0012_dashboard_widgets_width32
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_scan_schedule"
down_revision = "0012_dashboard_widgets_width32"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    op.add_column("scan_groups",
                  sa.Column("schedule_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.false()),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("schedule_mode", sa.String(16), nullable=False,
                            server_default="interval"),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("schedule_interval_min", sa.Integer(), nullable=False,
                            server_default="360"),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("schedule_time", sa.String(5), nullable=True),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("schedule_days", sa.String(20), nullable=True),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
                  schema=SCHEMA)
    op.add_column("scan_groups",
                  sa.Column("last_schedule_at", sa.DateTime(timezone=True), nullable=True),
                  schema=SCHEMA)
    op.create_index("ix_rani_inventory_scan_groups_due", "scan_groups",
                    ["next_run_at"], schema=SCHEMA,
                    postgresql_where=sa.text("schedule_enabled AND enabled"))


def downgrade() -> None:
    op.drop_index("ix_rani_inventory_scan_groups_due", table_name="scan_groups",
                  schema=SCHEMA)
    for column in ("last_schedule_at", "next_run_at", "schedule_days",
                   "schedule_time", "schedule_interval_min", "schedule_mode",
                   "schedule_enabled"):
        op.drop_column("scan_groups", column, schema=SCHEMA)
