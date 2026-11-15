"""Asset actions (menu Setup → Actions) — ala Lansweeper Asset Pages.

Revision ID: 0007_asset_actions
Revises: 0006_users_ad
Create Date: 2026-11-15

Seed 10 action default (sama dengan perilaku sebelumnya), idempotent.
Tabel konfigurasi — tidak di-grant ke role `rani_report`.
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app import models

revision = "0007_asset_actions"
down_revision = "0006_users_ad"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"

# (name, command, kind, advanced, confirm, sort_order)
_DEFAULT_ACTIONS = [
    ("Buka di browser (HTTP)",  "http://{ipaddress}",       "link", False, False, 10),
    ("Buka di browser (HTTPS)", "https://{ipaddress}",      "link", False, False, 20),
    ("Buka berbagi file (C$)",  "file:///{ipaddress}/c$",   "link", False, True,  30),
    ("Remote Desktop (RDP)",    "rdp://{ipaddress}",        "link", False, True,  40),
    ("SSH",                     "ssh://{ipaddress}",        "link", False, True,  50),
    ("VNC",                     "vnc://{ipaddress}",        "link", False, True,  60),
    ("Salin `mstsc` untuk RDP", "mstsc /v:{ipaddress}",     "copy", False, False, 70),
    ("Salin alamat IP",         "{ipaddress}",              "copy", False, False, 80),
    ("Salin MAC",               "{mac}",                    "copy", False, False, 90),
    ("Salin hostname",          "{hostname}",               "copy", False, False, 100),
]


def upgrade() -> None:
    models.AssetAction.__table__.create(bind=op.get_bind(), checkfirst=True)
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    for name, command, kind, advanced, confirm, order in _DEFAULT_ACTIONS:
        exists = bind.execute(
            sa.text(f"SELECT 1 FROM {SCHEMA}.asset_actions WHERE name = :name"),
            {"name": name}).scalar_one_or_none()
        if exists:
            continue
        bind.execute(
            sa.text(f"""
                INSERT INTO {SCHEMA}.asset_actions
                    (id, name, command, kind, enabled, advanced, confirm,
                     sort_order, created_at, updated_at)
                VALUES (gen_random_uuid(), :name, :command, :kind, true, :advanced,
                        :confirm, :order, :now, :now)
            """),
            {"name": name, "command": command, "kind": kind,
             "advanced": advanced, "confirm": confirm, "order": order, "now": now},
        )
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rani_report') THEN
            EXECUTE 'REVOKE ALL ON {SCHEMA}.asset_actions FROM rani_report';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("asset_actions", schema=SCHEMA)
