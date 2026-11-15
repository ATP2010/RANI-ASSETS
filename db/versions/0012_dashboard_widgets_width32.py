"""Lebar widget dashboard diperbesar ke VARCHAR(32) (kelas grid gabungan).

Revision ID: 0012_dashboard_widgets_width32
Revises: 0011_seed_builtin_widgets
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_dashboard_widgets_width32"
down_revision = "0011_seed_builtin_widgets"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    op.alter_column("dashboard_widgets", "width",
                    existing_type=sa.String(16), type_=sa.String(32),
                    schema=SCHEMA)


def downgrade() -> None:
    op.alter_column("dashboard_widgets", "width",
                    existing_type=sa.String(32), type_=sa.String(16),
                    schema=SCHEMA)
