"""Port map Layer-2: endpoint_port_mappings (MAC ↔ port switch) + flag grup.

Revision ID: 0005_bridge_fdb
Revises: 0004_scan
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0005_bridge_fdb"
down_revision = "0004_scan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    models.EndpointPortMapping.__table__.create(bind=bind, checkfirst=True)
    op.add_column("scan_groups",
                  sa.Column("fdb_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.true()),
                  schema="rani_inventory")
    op.add_column("scan_results",
                  sa.Column("fdb_count", sa.Integer(), nullable=True),
                  schema="rani_inventory")
    # Role report read-only dibuat saat api start (boleh belum ada saat migrasi).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rani_report') THEN
            EXECUTE 'GRANT SELECT ON rani_inventory.endpoint_port_mappings TO rani_report';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_column("scan_results", "fdb_count", schema="rani_inventory")
    op.drop_column("scan_groups", "fdb_enabled", schema="rani_inventory")
    op.drop_table("endpoint_port_mappings", schema="rani_inventory")
