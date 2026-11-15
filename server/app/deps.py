"""Dependency auth: sesi DB + permission `modul.aksi` (union multi-role)."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AppUser, AppUserRole, AuthSession, Role
from app.permissions import union_permissions
from app.security import sha256_hex

COOKIE_NAME = "rani_session"


async def load_user_access(session: AsyncSession, user: AppUser) -> None:
    """Attach `user.perm_set` (set[str]) dan `user.role_slugs` (list[str])."""
    rows = (await session.execute(
        select(Role.slug, Role.permissions)
        .join(AppUserRole, AppUserRole.role_id == Role.id)
        .where(AppUserRole.user_id == user.id)
    )).all()
    slugs = [row.slug for row in rows]
    user.role_slugs = slugs
    user.perm_set = union_permissions([row.permissions for row in rows], slugs)


def has_perm(user: AppUser | None, perm: str) -> bool:
    return user is not None and perm in getattr(user, "perm_set", set())


async def _resolve(session: AsyncSession, raw: str | None) -> AppUser | None:
    if not raw:
        return None
    row = (await session.execute(
        select(AuthSession, AppUser)
        .join(AppUser, AppUser.id == AuthSession.user_id)
        .where(AuthSession.token_hash == sha256_hex(raw))
    )).first()
    if not row:
        return None
    sess_row, user = row
    now = datetime.now(timezone.utc)
    if sess_row.revoked_at or sess_row.expires_at <= now or not user.is_active:
        return None
    await load_user_access(session, user)
    return user


async def get_current_user(request: Request,
                           session: AsyncSession = Depends(get_session)) -> AppUser | None:
    user = await _resolve(session, request.cookies.get(COOKIE_NAME))
    if user is not None:
        request.state.user = user
    return user


async def get_current_user_ws(ws: WebSocket,
                              session: AsyncSession = Depends(get_session)) -> AppUser | None:
    return await _resolve(session, ws.cookies.get(COOKIE_NAME))


def require_user():
    """Hanya menuntut sesi valid (mis. halaman dokumentasi)."""
    async def _dep(user: AppUser | None = Depends(get_current_user)) -> AppUser:
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        return user

    return _dep


def require_perm(*perms: str):
    """Menuntut SEMUA permission yang disebutkan (kebanyakan route cuma satu)."""
    needed = tuple(perms)

    async def _dep(user: AppUser | None = Depends(get_current_user)) -> AppUser:
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        if not all(p in getattr(user, "perm_set", set()) for p in needed):
            raise HTTPException(status_code=403, detail="insufficient permission")
        return user

    return _dep
