"""Seed contoh action ber-kind `script` (khas Lansweeper: klik → PC pengguna).

Revision ID: 0008_seed_script_actions
Revises: 0007_asset_actions
Create Date: 2026-11-15

Seed `ping.bat {ipaddress}` (skrip tersedia di ./actions/ping.bat), idempotent.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0008_seed_script_actions"
down_revision = "0007_asset_actions"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    exists = bind.execute(
        sa.text(f"SELECT 1 FROM {SCHEMA}.asset_actions WHERE name = :n"),
        {"n": "Ping (skrip)"}).scalar_one_or_none()
    if exists:
        return
    bind.execute(
        sa.text(f"""
            INSERT INTO {SCHEMA}.asset_actions
                (id, name, command, kind, enabled, advanced, confirm, sort_order,
                 created_at, updated_at)
            VALUES (gen_random_uuid(), 'Ping (skrip)', 'ping.bat {{ipaddress}}',
                    'script', true, false, false, 110, :now, :now)
        """),
        {"now": now},
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM {SCHEMA}.asset_actions WHERE name = 'Ping (skrip)'")
