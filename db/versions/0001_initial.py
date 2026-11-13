"""initial schema rani_inventory

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-13

Skema didefinisikan di `app/models.py`; migrasi awal membuat schema + semua tabel
dari metadata (v1). Perubahan berikutnya WAJIB migrasi eksplisit (bukan create_all).
"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS rani_inventory")
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
    op.execute("DROP SCHEMA IF EXISTS rani_inventory CASCADE")