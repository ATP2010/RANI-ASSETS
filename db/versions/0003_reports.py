"""Tabel `reports` (custom report SQL) + seed contoh query bawaan.

Revision ID: 0003_reports
Revises: 0002_agent_secret_nullable
Create Date: 2026-11-14
"""
from alembic import op

from app import models  # noqa: F401

revision = "0003_reports"
down_revision = "0002_agent_secret_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    models.Report.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    models.Report.__table__.drop(bind=op.get_bind(), checkfirst=True)