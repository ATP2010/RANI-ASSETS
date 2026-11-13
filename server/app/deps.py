"""Dependency auth: sesi DB + RBAC sederhana (reader<operator<admin)."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AppUser, AuthSession
from app.security import role_allows, sha256_hex

COOKIE_NAME = "rani_session"


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


def require_user(minimum: str = "reader"):
    async def _dep(user: AppUser | None = Depends(get_current_user)) -> AppUser:
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        if not role_allows(user.role, minimum):
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return _dep