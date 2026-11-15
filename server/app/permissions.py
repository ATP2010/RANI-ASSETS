"""Katalog permission + default role bawaan + resolver union.

Permission efektif seorang user = union dari permission semua role yang
dimilikinya (multi-role). Role `admin` terkunci: selalu semua permission.
"""

PERMISSIONS: dict[str, str] = {
    "dashboard.view": "Melihat dashboard dan statistik",
    "assets.view": "Melihat daftar dan detail asset",
    "assets.export": "Export CSV asset",
    "reports.view": "Melihat daftar dan hasil report",
    "reports.run": "Menjalankan report",
    "reports.export": "Export CSV hasil report",
    "reports.manage": "Membuat/mengubah/menghapus report",
    "scan.view": "Melihat grup, riwayat, dan hasil scan",
    "scan.run": "Memulai/membatalkan scan",
    "scan.manage": "Mengelola grup IP, custom OID, port map",
    "portmap.view": "Halaman port map dan lookup MAC",
    "agents.view": "Halaman agent dan unduhan",
    "agents.manage": "Enrollment token dan revoke agent",
    "users.view": "Melihat daftar user dan sesi",
    "users.manage": "Menambah/mengubah/menonaktifkan user, reset password",
    "roles.view": "Melihat daftar role",
    "roles.manage": "Membuat/mengubah/menghapus role dan permission",
    "directory.view": "Melihat connector AD dan riwayat sync",
    "directory.manage": "Mengubah connector, test koneksi, mapping group",
    "directory.sync": "Menjalankan sync manual",
    "audit.view": "Melihat sesi aktif dan audit log",
    "setup.view": "Membuka menu Setup dan melihat konfigurasinya",
    "setup.manage": "Mengubah konfigurasi, mengelola actions asset",
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(PERMISSIONS)

_READER = (
    "dashboard.view",
    "assets.view", "assets.export",
    "reports.view", "reports.run", "reports.export",
    "scan.view",
    "portmap.view",
    "agents.view",
)

_OPERATOR = _READER + (
    "reports.manage",
    "scan.run", "scan.manage",
    "agents.manage",
)

# Role bawaan. `admin` permissions = semua (di-materialisasikan saat seed agar
# snapshot-nya jelas di DB), tetapi resolver tetap memaksa admin = semua.
DEFAULT_ROLES: list[dict] = [
    {"slug": "reader", "name": "Reader",
     "description": "Lihat dashboard, asset, report, scan, port map, agent",
     "permissions": list(_READER), "is_builtin": True},
    {"slug": "operator", "name": "Operator",
     "description": "Reader + kelola report, scan, dan agent (enrollment/revoke)",
     "permissions": list(_OPERATOR), "is_builtin": True},
    {"slug": "admin", "name": "Administrator",
     "description": "Akses penuh. Role terkunci: tidak bisa diubah/dihapus.",
     "permissions": list(ALL_PERMISSIONS), "is_builtin": True},
]

ADMIN_SLUG = "admin"


def normalize_permissions(values: list[str] | set[str] | None) -> list[str]:
    """Buang permission tak dikenal + duplikat; urutan stabil mengikuti katalog."""
    wanted = set(values or [])
    return [p for p in ALL_PERMISSIONS if p in wanted]


def union_permissions(role_perms: list[list[str]] | list[set[str]],
                      role_slugs: list[str] | None = None) -> set[str]:
    """Union permission dari semua role; slug `admin` selalu menang penuh."""
    slugs = set(role_slugs or [])
    if ADMIN_SLUG in slugs:
        return set(ALL_PERMISSIONS)
    out: set[str] = set()
    for perms in role_perms:
        out.update(perms or [])
    return out & set(ALL_PERMISSIONS)


def role_slugs_for(user_roles: list[str]) -> list[str]:
    return list(dict.fromkeys(user_roles))
