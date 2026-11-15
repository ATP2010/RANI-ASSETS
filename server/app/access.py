"""Guard anti-lockout F5 + helper revoke sesi.

Aturan kunci:
- Minimal satu user aktif harus selalu punya `users.manage` + `roles.manage`.
- Akun lokal seed (RANI_ADMIN_USER) tidak bisa dinonaktifkan/dihapus lewat UI.
- Mengubah password/role/status user mencabut semua sesi user tsb.
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AppUser, AppUserRole, AuthSession, Role
from app.permissions import union_permissions

settings = get_settings()

GUARD_PERMISSIONS = ("users.manage", "roles.manage")


async def _capabilities(session: AsyncSession) -> dict:
    """Map user_id -> union permission, hanya untuk user aktif."""
    rows = (await session.execute(
        select(AppUser.id, Role.slug, Role.permissions)
        .join(AppUserRole, AppUserRole.user_id == AppUser.id)
        .join(Role, Role.id == AppUserRole.role_id)
        .where(AppUser.is_active.is_(True))
    )).all()
    perms: dict = {}
    slugs: dict = {}
    for user_id, slug, permissions in rows:
        perms.setdefault(user_id, []).append(permissions or [])
        slugs.setdefault(user_id, []).append(slug)
    return {uid: union_permissions(plist, slugs[uid]) for uid, plist in perms.items()}


async def count_guard_capable(session: AsyncSession) -> int:
    caps = await _capabilities(session)
    return sum(1 for s in caps.values() if all(p in s for p in GUARD_PERMISSIONS))


async def is_last_guard(session: AsyncSession, user_id) -> bool:
    """True bila `user_id` adalah user aktif terakhir dengan kedua perm tsb."""
    caps = await _capabilities(session)
    capable = [uid for uid, s in caps.items() if all(p in s for p in GUARD_PERMISSIONS)]
    return len(capable) == 1 and capable[0] == user_id


def is_seed_admin(user: AppUser) -> bool:
    return (getattr(user, "auth_source", "local") == "local"
            and user.username == settings.RANI_ADMIN_USER)


async def revoke_sessions_for_user(session: AsyncSession, user_id) -> int:
    """Cabut semua sesi aktif user. Return jumlah yang dicabut."""
    result = await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0


async def would_lose_last_guard(session: AsyncSession, user: AppUser,
                                new_role_slugs: list[str]) -> bool:
    """True bila mengganti role `user` with `new_role_slugs` membuat tidak ada
    user aktif dengan users.manage+roles.manage tersisa."""
    caps = await _capabilities(session)
    def capable(uid, perm_override=None):
        s = perm_override if perm_override is not None else caps.get(uid, set())
        return all(p in s for p in GUARD_PERMISSIONS)
    currently = capable(user.id)
    rows = (await session.execute(
        select(Role.slug, Role.permissions)
        .where(Role.slug.in_(set(new_role_slugs))))).all()
    new_perms = union_permissions([r.permissions for r in rows],
                                  [r.slug for r in rows])
    others = sum(1 for uid in caps if uid != user.id and capable(uid))
    return currently and not capable(user.id, new_perms) and others == 0
