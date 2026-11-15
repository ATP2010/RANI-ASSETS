"""Lebar kolom widget dashboard diperbesar (col-lg-12 = 9 karakter).

Revision ID: 0010_dashboard_widgets_width
Revises: 0009_dashboard_widgets
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_dashboard_widgets_width"
down_revision = "0009_dashboard_widgets"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    op.alter_column("dashboard_widgets", "width",
                    existing_type=sa.String(8), type_=sa.String(16),
                    schema=SCHEMA)


def downgrade() -> None:
    op.alter_column("dashboard_widgets", "width",
                    existing_type=sa.String(16), type_=sa.String(8),
                    schema=SCHEMA)
