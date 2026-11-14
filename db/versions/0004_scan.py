"""Scan SNMP: grup IP, custom OID, run + hasil. Menggantikan tabel stub scan_targets.

Revision ID: 0004_scan
Revises: 0003_reports
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

from app import models

revision = "0004_scan"
down_revision = "0003_reports"
branch_labels = None
depends_on = None

NEW_TABLES = (models.ScanGroup.__table__, models.ScanOid.__table__,
              models.ScanRun.__table__, models.ScanResult.__table__)


def upgrade() -> None:
    bind = op.get_bind()
    # scan_targets hanya stub F2 dan tidak pernah dipakai — digantikan tabel di bawah.
    op.execute("DROP TABLE IF EXISTS rani_inventory.scan_targets CASCADE")
    for table in NEW_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS rani_inventory.{table.name} CASCADE")
    op.create_table(
        "scan_targets",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("cidr", sa.String(64), nullable=False),
        sa.Column("snmp_version", sa.String(8), nullable=False, server_default="2c"),
        sa.Column("community_enc", sa.Text),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_scan_at", sa.DateTime(timezone=True)),
        sa.Column("last_scan_status", sa.String(32)),
        sa.Column("stats", sa.dialects.postgresql.JSONB, server_default="{}"),
        schema="rani_inventory",
    )