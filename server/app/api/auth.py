"""Login/logout UI (session cookie di DB). Routing: username polos = lokal;
DOMAIN\\user / UPN = Active Directory (F5.6)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app import directory as ad
from app.adsync import _replace_roles, _upsert_ad_user
from app.audit import audit, client_ip
from app.config import get_settings
from app.db import get_session
from app.deps import COOKIE_NAME, load_user_access
from app.models import (AppUser, AuthSession, DirectoryConnector,
                        DirectoryGroupRole, Role)
from app.security import new_token, sha256_hex, verify_password
from app.templating import templates

router = APIRouter(tags=["auth"])
settings = get_settings()


@router.get("/login")
async def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


async def _redis_incr_window(redis: Redis, key: str, limit: int, seconds: int) -> bool:
    """True bila masih di bawah limit. Pakai window tetap per key."""
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, seconds)
    return attempts <= limit


def _ad_authenticate(connector, parsed: dict, password: str):
    """Sync LDAP (dipanggil via threadpool). Return (found|None, reason|None)."""
    try:
        found = ad.find_user(connector, parsed["sam"])
    except Exception as exc:  # noqa: BLE001 — server AD turun dll.
        return None, f"ad_unreachable: {exc}"
    if not found:
        return None, "not_found"
    if not ad.user_enabled(found["uac"]):
        return None, "disabled"
    if not ad.bind_as_user(connector, found["dn"], password):
        return None, "bad_password"
    try:
        groups = ad.group_dns_for_user(connector, found["dn"])
    except Exception as exc:  # noqa: BLE001
        return None, f"ad_unreachable: {exc}"
    return {**found, "groups": groups}, None


async def _login_failure(request: Request, session: AsyncSession, login_page_ctx: dict,
                         *, actor: str, reason: str, source: str):
    await audit(session, request, actor=actor, action="login", outcome="failure",
                details={"reason": reason, "source": source})
    await session.commit()
    return templates.TemplateResponse(request, "login.html", login_page_ctx,
                                      status_code=401)


async def _find_connector(session: AsyncSession, parsed: dict):
    rows = (await session.execute(
        select(DirectoryConnector).where(DirectoryConnector.enabled.is_(True)))).scalars().all()
    if parsed["match"] == "netbios":
        return next((c for c in rows
                     if (c.domain or "").lower() == parsed["domain"]), None)
    return next((c for c in rows
                 if (c.domain_fqdn or "").lower() == parsed["domain"]), None)


async def _mapped_roles(session: AsyncSession, connector_id, group_dns: list[str]):
    if not group_dns:
        return [], []
    keys = {ad.dn_key(g) for g in group_dns}
    rows = (await session.execute(
        select(DirectoryGroupRole, Role.slug)
        .join(Role, Role.id == DirectoryGroupRole.role_id)
        .where(DirectoryGroupRole.connector_id == connector_id,
               DirectoryGroupRole.enabled.is_(True)))).all()
    role_ids, slugs = [], []
    for mapping, slug in rows:
        if ad.dn_key(mapping.group_dn) in keys:
            role_ids.append(mapping.role_id)
            slugs.append(slug)
    return sorted(set(role_ids), key=str), sorted(set(slugs))


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...),
                       next: str = Form("/"),
                       session: AsyncSession = Depends(get_session)):
    redis: Redis = request.app.state.redis
    settings_local = settings
    ip = client_ip(request) or "unknown"
    raw_username = (username or "").strip()
    limit = settings_local.RANI_LOGIN_MAX_ATTEMPTS
    ctx = {"next": next, "error": "username/password salah"}
    if not await _redis_incr_window(redis, f"rani:login:ip:{ip}", limit, 300):
        return templates.TemplateResponse(request, "login.html",
                                          {"next": next,
                                           "error": "terlalu banyak percobaan, tunggu 5 menit"},
                                          status_code=429)
    if not await _redis_incr_window(redis, f"rani:login:u:{raw_username.lower()[:64]}",
                                    limit, 300):
        return templates.TemplateResponse(request, "login.html",
                                          {"next": next,
                                           "error": "terlalu banyak percobaan, tunggu 5 menit"},
                                          status_code=429)

    parsed = ad.parse_login_username(raw_username)
    if parsed is None:
        return await _login_failure(request, session, ctx,
                                    actor=raw_username[:64], reason="bad_format",
                                    source="unknown")

    if parsed["kind"] == "local":
        if not settings_local.RANI_AUTH_LOCAL_ENABLED:
            return await _login_failure(request, session, ctx,
                                        actor=raw_username[:64], reason="local_disabled",
                                        source="local")
        user = (await session.execute(
            select(AppUser).where(AppUser.username == parsed["sam"],
                                  AppUser.auth_source == "local")
        )).scalar_one_or_none()
        if user is None or not user.is_active \
                or not verify_password(password, user.password_hash):
            return await _login_failure(request, session, ctx,
                                        actor=parsed["sam"][:64],
                                        reason="bad_password" if user else "not_found",
                                        source="local")
        await load_user_access(session, user)
        raw = new_token(32)
        now = datetime.now(timezone.utc)
        session.add(AuthSession(token_hash=sha256_hex(raw), user_id=user.id,
                                created_at=now,
                                expires_at=now + timedelta(hours=settings_local.RANI_SESSION_TTL_H),
                                request_ip=ip, auth_source="local"))
        user.last_login_at = now
        roles = list(getattr(user, "role_slugs", []))
        await audit(session, request, actor=user.username, action="login",
                    details={"roles": roles, "source": "local"})
        await session.commit()
        await redis.delete(f"rani:login:ip:{ip}")
        await redis.delete(f"rani:login:u:{raw_username.lower()[:64]}")

        target = next if next.startswith("/") and not next.startswith("//") else "/"
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(COOKIE_NAME, raw, httponly=True, samesite="lax",
                            max_age=settings_local.RANI_SESSION_TTL_H * 3600, path="/")
        return response

    # ------------------------------------------------------------- AD login
    if not settings_local.RANI_AD_ENABLED:
        return await _login_failure(request, session, ctx,
                                    actor=raw_username[:64], reason="ad_disabled",
                                    source="ad")
    connector = await _find_connector(session, parsed)
    if connector is None:
        return await _login_failure(request, session, ctx,
                                    actor=raw_username[:64], reason="connector_not_found",
                                    source="ad")
    found, reason = await run_in_threadpool(_ad_authenticate, connector, parsed, password)
    if found is None:
        return await _login_failure(request, session, ctx,
                                    actor=raw_username[:64], reason=reason or "ad_error",
                                    source="ad")

    role_ids, role_slugs = await _mapped_roles(session, connector.id, found["groups"])
    if not role_ids:
        return await _login_failure(request, session, ctx,
                                    actor=f"{connector.domain.lower()}\\{parsed['sam']}"[:64],
                                    reason="no_mapped_group", source="ad")

    now = datetime.now(timezone.utc)
    username_db = f"{connector.domain.lower()}\\{parsed['sam']}"[:64]
    _, user = await _upsert_ad_user(session, connector, found, username_db, now)
    await _replace_roles(session, user, role_ids)
    user.last_login_at = now

    raw = new_token(32)
    session.add(AuthSession(token_hash=sha256_hex(raw), user_id=user.id,
                            created_at=now,
                            expires_at=now + timedelta(hours=settings_local.RANI_SESSION_TTL_H),
                            request_ip=ip, auth_source="ad"))
    await audit(session, request, actor=user.username, action="login",
                details={"roles": role_slugs, "source": "ad", "domain": connector.domain})
    await session.commit()
    await redis.delete(f"rani:login:ip:{ip}")
    await redis.delete(f"rani:login:u:{raw_username.lower()[:64]}")

    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(COOKIE_NAME, raw, httponly=True, samesite="lax",
                        max_age=settings_local.RANI_SESSION_TTL_H * 3600, path="/")
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