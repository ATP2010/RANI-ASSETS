"""agents.secret_enc boleh NULL untuk agent mode langsung (tanpa enroll).

Revision ID: 0002_agent_secret_nullable
Revises: 0001_initial
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_agent_secret_nullable"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agents", "secret_enc", existing_type=sa.Text(),
                    nullable=True, schema="rani_inventory")


def downgrade() -> None:
    op.execute("UPDATE rani_inventory.agents SET secret_enc = '' WHERE secret_enc IS NULL")
    op.alter_column("agents", "secret_enc", existing_type=sa.Text(),
                    nullable=False, schema="rani_inventory")