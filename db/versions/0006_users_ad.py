"""Users & akses fase 5: roles, app_user_roles, connector AD, sync run.

Revision ID: 0006_users_ad
Revises: 0005_bridge_fdb
Create Date: 2026-11-15

Langkah:
1. Buat tabel roles, app_user_roles, directory_connectors, directory_group_roles,
   directory_sync_runs (+ kolom auth_source di auth_sessions, kolom baru di app_users).
2. Backfill: app_users.role lama -> app_user_roles (reader/operator/admin).
3. Seed role bawaan (idempotent) dan hapus kolom string app_users.role.

Tabel kredensial TIDAK di-grant ke role `rani_report`.
"""
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app import models
from app.permissions import DEFAULT_ROLES

revision = "0006_users_ad"
down_revision = "0005_bridge_fdb"
branch_labels = None
depends_on = None

SCHEMA = "rani_inventory"


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Tabel baru (checkfirst agar aman bila pernah dibuat manual)
    for table in (models.Role.__table__, models.AppUserRole.__table__,
                  models.DirectoryConnector.__table__, models.DirectoryGroupRole.__table__,
                  models.DirectorySyncRun.__table__):
        table.create(bind=bind, checkfirst=True)

    # 2) Kolom baru app_users (idempotent: tabel mungkin sudah dibuat dari models)
    for stmt in (
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS auth_source VARCHAR(8) NOT NULL DEFAULT 'local'",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS domain VARCHAR(64)",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS sam_account_name VARCHAR(64)",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS upn VARCHAR(255)",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS object_guid VARCHAR(64)",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "ALTER TABLE rani_inventory.app_users ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ",
    ):
        op.execute(stmt)
    op.alter_column("app_users", "password_hash", nullable=True, schema=SCHEMA)

    # 3) auth_sessions.auth_source
    op.execute(
        "ALTER TABLE rani_inventory.auth_sessions "
        "ADD COLUMN IF NOT EXISTS auth_source VARCHAR(8) NOT NULL DEFAULT 'local'"
    )

    # 4) Seed role bawaan (idempotent)
    now = datetime.now(timezone.utc)
    for spec in DEFAULT_ROLES:
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.roles (id, slug, name, description, permissions,
                                            is_builtin, created_at, updated_at)
                VALUES (gen_random_uuid(), :slug, :name, :description, CAST(:perms AS jsonb),
                        true, :now, :now)
                ON CONFLICT (slug) DO NOTHING
                """
            ),
            {"slug": spec["slug"], "name": spec["name"], "description": spec["description"],
             "perms": json.dumps(spec["permissions"]), "now": now},
        )

    # 5) Backfill app_users.role -> app_user_roles (hanya bila kolom legacy role ada)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema = '{SCHEMA}' AND table_name = 'app_users'
                       AND column_name = 'role') THEN
            INSERT INTO {SCHEMA}.app_user_roles (user_id, role_id)
            SELECT u.id, r.id
            FROM {SCHEMA}.app_users u
            JOIN {SCHEMA}.roles r
              ON r.slug = CASE u.role WHEN 'admin' THEN 'admin'
                                      WHEN 'operator' THEN 'operator'
                                      ELSE 'reader' END
            ON CONFLICT DO NOTHING;
          END IF;
        END $$;
        """
    )

    # 6) Hapus kolom string role lama (jika ada)
    op.execute(f"ALTER TABLE {SCHEMA}.app_users DROP COLUMN IF EXISTS role")


def downgrade() -> None:
    bind = op.get_bind()
    # Kembalikan kolom role (dari app_user_roles; prioritas admin > operator > reader)
    op.add_column("app_users", sa.Column("role", sa.String(16), nullable=True), schema=SCHEMA)
    op.execute(
        f"""
        UPDATE {SCHEMA}.app_users u SET role = sub.slug FROM (
            SELECT DISTINCT ON (aur.user_id) aur.user_id, r.slug
            FROM {SCHEMA}.app_user_roles aur JOIN {SCHEMA}.roles r ON r.id = aur.role_id
            ORDER BY aur.user_id,
                     CASE r.slug WHEN 'admin' THEN 0 WHEN 'operator' THEN 1 ELSE 2 END
        ) sub WHERE u.id = sub.user_id
        """
    )
    op.execute(f"UPDATE {SCHEMA}.app_users SET role = 'reader' WHERE role IS NULL")
    op.alter_column("app_users", "role", nullable=False, schema=SCHEMA)

    # password_hash kembali NOT NULL (user AD diberi hash dummy terkunci)
    op.execute(f"UPDATE {SCHEMA}.app_users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("app_users", "password_hash", nullable=False, schema=SCHEMA)

    op.drop_column("auth_sessions", "auth_source", schema=SCHEMA)
    for col in ("last_sync_at", "updated_at", "email", "object_guid", "upn",
                "sam_account_name", "domain", "auth_source"):
        op.drop_column("app_users", col, schema=SCHEMA)

    for table in ("directory_sync_runs", "directory_group_roles", "directory_connectors",
                  "app_user_roles", "roles"):
        op.drop_table(table, schema=SCHEMA)
