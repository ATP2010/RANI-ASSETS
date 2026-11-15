"""Login/logout UI (session cookie di DB)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit, client_ip
from app.config import get_settings
from app.db import get_session
from app.deps import COOKIE_NAME
from app.models import AppUser, AuthSession
from app.security import new_token, sha256_hex, verify_password
from app.templating import templates

router = APIRouter(tags=["auth"])
settings = get_settings()


@router.get("/login")
async def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...),
                       next: str = Form("/"),
                       session: AsyncSession = Depends(get_session)):
    redis: Redis = request.app.state.redis
    ip = client_ip(request) or "unknown"
    attempts = await redis.incr(f"rani:login:{ip}")
    if attempts == 1:
        await redis.expire(f"rani:login:{ip}", 300)
    if attempts > 20:
        return templates.TemplateResponse(request, "login.html",
                                          {"next": next, "error": "terlalu banyak percobaan, tunggu 5 menit"},
                                          status_code=429)

    user = (await session.execute(
        select(AppUser).where(AppUser.username == username.strip())
    )).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        await audit(session, request, actor=username[:64], action="login", outcome="failure")
        await session.commit()
        return templates.TemplateResponse(request, "login.html",
                                          {"next": next, "error": "username/password salah"},
                                          status_code=401)

    raw = new_token(32)
    now = datetime.now(timezone.utc)
    session.add(AuthSession(token_hash=sha256_hex(raw), user_id=user.id, created_at=now,
                            expires_at=now + timedelta(hours=settings.RANI_SESSION_TTL_H),
                            request_ip=ip))
    user.last_login_at = now
    await audit(session, request, actor=user.username, action="login",
                details={"roles": list(getattr(user, "role_slugs", []))})
    await session.commit()
    await redis.delete(f"rani:login:{ip}")

    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(COOKIE_NAME, raw, httponly=True, samesite="lax",
                        max_age=settings.RANI_SESSION_TTL_H * 3600, path="/")
    return response


@router.post("/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        row = await session.get(AuthSession, sha256_hex(raw))
        if row:
            row.revoked_at = datetime.now(timezone.utc)
            await audit(session, request, actor=str(row.user_id), action="logout")
            await session.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response