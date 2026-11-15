"""Dashboard custom widgets (menu Setup → Dashboard).

Revision ID: 0009_dashboard_widgets
Revises: 0008_seed_script_actions
Create Date: 2026-11-15

Widget sumber datanya = report SQL tersimpan (menu Reports). Dijalankan
read-only seperti report biasa. Tidak ada seed (dashboard custom kosong).
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0009_dashboard_widgets"
down_revision = "0008_seed_script_actions"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    bind = op.get_bind()
    models.DashboardWidget.__table__.create(bind=bind, checkfirst=True)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rani_report') THEN
            EXECUTE 'REVOKE ALL ON {SCHEMA}.dashboard_widgets FROM rani_report';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("dashboard_widgets", schema=SCHEMA)
