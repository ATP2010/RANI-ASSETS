"""Seed widget bawaan dashboard (kind `kpi-*`/`chart-*`/`recent-events`).

Revision ID: 0011_seed_builtin_widgets
Revises: 0010_dashboard_widgets_width
Create Date: 2026-11-15

Meniru tampilan dashboard bawaan sebelumnya. Idempotent: hanya menyisip baris
yang kind-nya belum ada.
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0011_seed_builtin_widgets"
down_revision = "0010_dashboard_widgets_width"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"

# (title, kind, width, sort_order)
_BUILTIN = [
    ("Total aset",                     "kpi-total",     "col-xl-3", 10),
    ("Online",                         "kpi-online",    "col-xl-3", 20),
    ("Offline",                        "kpi-offline",   "col-xl-3", 30),
    ("Judul software",                 "kpi-software",  "col-xl-3", 40),
    ("Distribusi OS",                  "chart-os",      "col-lg-4",          50),
    ("Status aset",                    "chart-status",  "col-lg-4",          60),
    ("Top software (jumlah aset)",     "chart-software", "col-lg-4",          70),
    ("Push masuk 24 jam",              "chart-trend",   "col-lg-7",          80),
    ("Perubahan software terakhir",    "recent-events", "col-lg-5",          90),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    for title, kind, width, order in _BUILTIN:
        exists = bind.execute(
            sa.text(f"SELECT 1 FROM {SCHEMA}.dashboard_widgets WHERE kind = :k"),
            {"k": kind}).scalar_one_or_none()
        if exists:
            continue
        bind.execute(
            sa.text(f"""
                INSERT INTO {SCHEMA}.dashboard_widgets
                    (id, title, kind, report_id, x_col, y_col, width,
                     sort_order, enabled, created_at, updated_at)
                VALUES (gen_random_uuid(), :title, :kind, NULL, NULL, NULL, :width,
                        :order, true, :now, :now)
            """),
            {"title": title, "kind": kind, "width": width,
             "order": order, "now": now},
        )


def downgrade() -> None:
    kinds = ", ".join(f"'{k}'" for _, k, _, _ in _BUILTIN)
    op.execute(f"DELETE FROM {SCHEMA}.dashboard_widgets WHERE kind IN ({kinds})")
