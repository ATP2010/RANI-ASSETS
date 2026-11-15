"""Menu Users (F5): daftar user, CRUD lokal, reset password, role custom, sesi.

Halaman server-rendered + JSON API /api/v1. Permission `users.*`, `roles.*`,
`audit.view` — bukan lagi rank role.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (count_guard_capable, is_last_guard, is_seed_admin,
                        revoke_sessions_for_user, would_lose_last_guard)
from app.audit import audit
from app.config import get_settings
from app.db import get_session
from app.deps import require_perm
from app.models import (AppUser, AppUserRole, AuthSession, AuditLog,
                        DirectoryGroupRole, Role)
from app.permissions import (ALL_PERMISSIONS, DEFAULT_ROLES, PERMISSIONS,
                             normalize_permissions)
from app.security import hash_password
from app.templating import templates

log = logging.getLogger("rani.users")
router = APIRouter(include_in_schema=False)
api_router = APIRouter(prefix="/api/v1", tags=["users"])
settings = get_settings()

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,64}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
MAX_NAME = 96


# ---------------------------------------------------------------- helpers
def _permission_groups() -> dict:
    groups: dict[str, list[tuple[str, str]]] = {}
    for key, desc in PERMISSIONS.items():
        groups.setdefault(key.split(".", 1)[0], []).append((key, desc))
    return groups


async def _roles_map(session: AsyncSession) -> dict:
    rows = (await session.execute(select(Role).order_by(Role.slug))).scalars().all()
    return {r.slug: r for r in rows}


async def _user_roles(session: AsyncSession, user_ids) -> dict:
    if not user_ids:
        return {}
    rows = (await session.execute(
        select(AppUserRole.user_id, Role.slug)
        .join(Role, Role.id == AppUserRole.role_id)
        .where(AppUserRole.user_id.in_(list(user_ids)))
    )).all()
    out: dict = {}
    for uid, slug in rows:
        out.setdefault(uid, []).append(slug)
    return out


async def _load_user_or_404(session: AsyncSession, user_id: str) -> AppUser:
    try:
        parsed = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="user tidak ditemukan") from None
    user = await session.get(AppUser, parsed)
    if user is None:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return user


async def _set_user_roles(session: AsyncSession, user: AppUser, slugs: list[str]) -> None:
    wanted = set(slugs or [])
    rows = (await session.execute(
        select(Role).where(Role.slug.in_(wanted)))).scalars().all()
    if len(rows) != len(wanted):
        missing = wanted - {r.slug for r in rows}
        raise HTTPException(status_code=400, detail=f"role tidak dikenal: {', '.join(sorted(missing))}")
    await session.execute(
        AppUserRole.__table__.delete().where(AppUserRole.user_id == user.id))
    for role in rows:
        session.add(AppUserRole(user_id=user.id, role_id=role.id))


async def _guard_disable(session: AsyncSession, user: AppUser) -> None:
    if is_seed_admin(user):
        raise HTTPException(status_code=403,
                            detail="akun admin seed tidak bisa dinonaktifkan/dihapus")
    if await is_last_guard(session, user.id):
        raise HTTPException(
            status_code=409,
            detail="ditolak: user ini satu-satunya yang aktif dengan users.manage + "
                   "roles.manage (anti-lockout)")


def _local_username(raw: str) -> str:
    return (raw or "").strip().lower()


def _validate_local_username(username: str) -> str | None:
    if not USERNAME_RE.match(username):
        return "username 3–64 karakter: huruf kecil/angka/titik/-/_; tanpa \\ atau @ (direservasi AD)"
    return None


def _check_password(password: str) -> str | None:
    if len(password or "") < settings.RANI_PASSWORD_MIN_LEN:
        return f"password minimal {settings.RANI_PASSWORD_MIN_LEN} karakter"
    return None


# ---------------------------------------------------------------- UI: /users
@router.get("/users")
async def users_page(request: Request, q: str | None = None,
                     status: str | None = None, source: str | None = None,
                     saved: int = 0, error: str | None = None,
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("users.view"))):
    stmt = select(AppUser).order_by(AppUser.username)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(AppUser.username.ilike(like)
                          | AppUser.display_name.ilike(like)
                          | (AppUser.email.ilike(like)))
    if status == "active":
        stmt = stmt.where(AppUser.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(AppUser.is_active.is_(False))
    if source in ("local", "ad"):
        stmt = stmt.where(AppUser.auth_source == source)
    users = (await session.execute(stmt)).scalars().all()
    roles_map = await _roles_map(session)
    roles_by_user = await _user_roles(session, [u.id for u in users])
    can_manage = "users.manage" in user.perm_set
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "active": "users", "sub": "users",
        "users": users, "roles_map": roles_map, "roles_by_user": roles_by_user,
        "q": q or "", "status": status or "", "source": source or "",
        "saved": bool(saved), "error": error, "can_manage": can_manage,
        "password_min_len": settings.RANI_PASSWORD_MIN_LEN,
        "seed_admin": settings.RANI_ADMIN_USER,
    })


@router.post("/users")
async def users_create(request: Request,
                       username: str = Form(""), display_name: str = Form(""),
                       email: str = Form(""), password: str = Form(""),
                       roles: list[str] = Form([]),
                       session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("users.manage"))):
    username = _local_username(username)
    error = _validate_local_username(username) or _check_password(password)
    if error:
        return RedirectResponse(f"/users?error={error[:150]}", status_code=303)
    if not roles:
        return RedirectResponse("/users?error=pilih+minimal+satu+role", status_code=303)
    new_user = AppUser(username=username, display_name=display_name.strip()[:128] or None,
                       email=email.strip()[:255] or None,
                       password_hash=hash_password(password), auth_source="local")
    session.add(new_user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return RedirectResponse(f"/users?error=username+{username}+sudah+dipakai",
                                status_code=303)
    await _set_user_roles(session, new_user, roles)
    await audit(session, request, actor=user.username, action="user.create",
                target=username, details={"roles": roles})
    await session.commit()
    return RedirectResponse("/users?saved=1", status_code=303)


# ---------------------------------------------------------------- UI: /users/roles
async def _role_user_counts(session: AsyncSession) -> dict:
    rows = (await session.execute(
        select(AppUserRole.role_id, func.count(AppUserRole.user_id))
        .group_by(AppUserRole.role_id))).all()
    return {role_id: count for role_id, count in rows}


async def _load_role_or_404(session: AsyncSession, role_id: str) -> Role:
    try:
        parsed = uuid.UUID(role_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="role tidak ditemukan") from None
    role = await session.get(Role, parsed)
    if role is None:
        raise HTTPException(status_code=404, detail="role tidak ditemukan")
    return role


async def _directory_mapping_counts(session: AsyncSession) -> dict:
    rows = (await session.execute(
        select(DirectoryGroupRole.role_id, func.count(DirectoryGroupRole.id))
        .group_by(DirectoryGroupRole.role_id))).all()
    return {role_id: count for role_id, count in rows}


def _role_dict(role: Role, users_count: int, mappings_count: int) -> dict:
    return {"role": role, "users": users_count, "mappings": mappings_count}


@router.get("/users/roles")
async def roles_page(request: Request, saved: int = 0, error: str | None = None,
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("roles.view"))):
    roles = (await session.execute(select(Role).order_by(Role.slug))).scalars().all()
    counts = await _role_user_counts(session)
    mappings = await _directory_mapping_counts(session)
    can_manage = "roles.manage" in user.perm_set
    return templates.TemplateResponse(request, "roles.html", {
        "user": user, "active": "users", "sub": "roles",
        "rows": [_role_dict(r, counts.get(r.id, 0), mappings.get(r.id, 0)) for r in roles],
        "saved": bool(saved), "error": error, "can_manage": can_manage,
        "permission_groups": _permission_groups(),
        "builtin_slugs": [r["slug"] for r in DEFAULT_ROLES],
    })


@router.post("/users/roles")
async def roles_create(request: Request,
                       name: str = Form(""), slug: str = Form(""),
                       description: str = Form(""),
                       permissions: list[str] = Form([]),
                       session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("roles.manage"))):
    slug = (slug or "").strip().lower()
    name = (name or "").strip()[:MAX_NAME]
    error = None
    if not SLUG_RE.match(slug):
        error = "slug 2–64 karakter: huruf kecil/angka/-; diawali huruf/angka"
    elif slug in {r["slug"] for r in DEFAULT_ROLES}:
        error = f"slug '{slug}' direservasi untuk role bawaan"
    elif not name:
        error = "nama role wajib diisi"
    if error:
        return RedirectResponse(f"/users/roles?error={error[:150]}", status_code=303)
    role = Role(slug=slug, name=name,
                description=description.strip()[:500] or None,
                permissions=normalize_permissions(permissions),
                is_builtin=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc))
    session.add(role)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return RedirectResponse(f"/users/roles?error=slug+'{slug}'+sudah+dipakai",
                                status_code=303)
    await audit(session, request, actor=user.username, action="role.create",
                target=slug, details={"permissions": role.permissions, "name": name})
    await session.commit()
    return RedirectResponse(f"/users/roles/{role.id}?saved=1", status_code=303)


@router.get("/users/roles/{role_id}")
async def roles_edit(role_id: str, request: Request, saved: int = 0,
                     error: str | None = None,
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("roles.view"))):
    role = await _load_role_or_404(session, role_id)
    counts = await _role_user_counts(session)
    mappings = await _directory_mapping_counts(session)
    can_manage = "roles.manage" in user.perm_set
    locked = role.slug == "admin" or not can_manage
    return templates.TemplateResponse(request, "role_form.html", {
        "user": user, "active": "users", "sub": "roles", "role": role,
        "users_count": counts.get(role.id, 0), "mappings_count": mappings.get(role.id, 0),
        "saved": bool(saved), "error": error,
        "locked": locked, "can_manage": can_manage,
        "permission_groups": _permission_groups(),
        "role_permissions": list(role.permissions or []),
    })


@router.post("/users/roles/{role_id}")
async def roles_update(role_id: str, request: Request,
                       name: str = Form(""), description: str = Form(""),
                       permissions: list[str] = Form([]),
                       session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("roles.manage"))):
    role = await _load_role_or_404(session, role_id)
    if role.slug == "admin":
        raise HTTPException(status_code=403,
                            detail="role admin terkunci: selalu semua permission")
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        return RedirectResponse(f"/users/roles/{role.id}?error=nama+role+wajib+diisi",
                                status_code=303)
    role.name = name
    role.description = description.strip()[:500] or None
    role.permissions = normalize_permissions(permissions)
    role.updated_at = datetime.now(timezone.utc)
    await session.flush()
    if await count_guard_capable(session) == 0:
        raise HTTPException(
            status_code=409,
            detail="ditolak: perubahan permission ini menghilangkan satu-satunya user "
                   "aktif dengan users.manage + roles.manage (anti-lockout)")
    await audit(session, request, actor=user.username, action="role.update",
                target=role.slug,
                details={"permissions": role.permissions, "name": name})
    await session.commit()
    return RedirectResponse(f"/users/roles/{role.id}?saved=1", status_code=303)


@router.post("/users/roles/{role_id}/duplicate")
async def roles_duplicate(role_id: str, request: Request,
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("roles.manage"))):
    source = await _load_role_or_404(session, role_id)
    base = f"{source.slug}-copy"
    slug = base
    suffix = 2
    while (await session.execute(
            select(Role.id).where(Role.slug == slug))).scalar_one_or_none():
        slug = f"{base}-{suffix}"
        suffix += 1
    clone = Role(slug=slug, name=f"Salinan {source.name}"[:MAX_NAME],
                 description=source.description,
                 permissions=list(source.permissions or []),
                 is_builtin=False,
                 created_at=datetime.now(timezone.utc),
                 updated_at=datetime.now(timezone.utc))
    session.add(clone)
    await audit(session, request, actor=user.username, action="role.create",
                target=slug,
                details={"permissions": clone.permissions, "duplicated_from": source.slug})
    await session.commit()
    return RedirectResponse(f"/users/roles/{clone.id}?saved=1", status_code=303)


@router.post("/users/roles/{role_id}/delete")
async def roles_delete(role_id: str, request: Request,
                       session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("roles.manage"))):
    role = await _load_role_or_404(session, role_id)
    if role.is_builtin:
        raise HTTPException(status_code=403, detail="role bawaan tidak bisa dihapus")
    users_count = (await session.execute(
        select(func.count(AppUserRole.user_id))
        .where(AppUserRole.role_id == role.id))).scalar_one()
    if users_count:
        raise HTTPException(
            status_code=409,
            detail=f"role masih dipakai {users_count} user — cabut dulu dari user tsb")
    mappings = (await session.execute(
        select(func.count(DirectoryGroupRole.id))
        .where(DirectoryGroupRole.role_id == role.id))).scalar_one()
    if mappings:
        raise HTTPException(
            status_code=409,
            detail=f"role masih dipakai {mappings} mapping group AD — hapus mapping dulu")
    await session.delete(role)
    await audit(session, request, actor=user.username, action="role.delete",
                target=role.slug)
    await session.commit()
    return RedirectResponse("/users/roles?saved=1", status_code=303)


# ---------------------------------------------------------------- UI: /users/sessions
@router.get("/users/sessions")
async def sessions_page(request: Request, action: str | None = None,
                        outcome: str | None = None, saved: int = 0,
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("audit.view"))):
    now = datetime.now(timezone.utc)
    rows = (await session.execute(
        select(AuthSession, AppUser.username, AppUser.auth_source)
        .join(AppUser, AppUser.id == AuthSession.user_id)
        .where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
        .order_by(AuthSession.created_at.desc()).limit(200))).all()
    audit_stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
    if action:
        audit_stmt = audit_stmt.where(AuditLog.action == action)
    if outcome:
        audit_stmt = audit_stmt.where(AuditLog.outcome == outcome)
    logs = (await session.execute(audit_stmt)).scalars().all()
    can_manage = "users.manage" in user.perm_set
    return templates.TemplateResponse(request, "sessions.html", {
        "user": user, "active": "users", "sub": "sessions",
        "rows": [{"session": s, "username": uname, "source": src,
                  "sid": s.token_hash[:16]} for s, uname, src in rows],
        "logs": logs, "saved": bool(saved), "can_manage": can_manage,
        "action": action or "", "outcome": outcome or "",
    })


@router.post("/users/sessions/{sid}/revoke")
async def sessions_revoke(sid: str, request: Request,
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("users.manage"))):
    sid = (sid or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16}", sid):
        raise HTTPException(status_code=400, detail="sid tidak valid")
    row = (await session.execute(
        select(AuthSession).where(AuthSession.token_hash.like(f"{sid}%")))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="sesi tidak ditemukan")
    owner = (await session.execute(
        select(AppUser.username).where(AppUser.id == row.user_id))).scalar_one()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    await audit(session, request, actor=user.username, action="session.revoke",
                target=owner, details={"sid": sid})
    await session.commit()
    return RedirectResponse("/users/sessions?saved=1", status_code=303)



@router.get("/users/{user_id}")
async def user_detail(user_id: str, request: Request,
                      saved: int = 0, error: str | None = None,
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("users.view"))):
    target = await _load_user_or_404(session, user_id)
    roles_map = await _roles_map(session)
    roles_by_user = await _user_roles(session, [target.id])
    active_sessions = (await session.execute(
        select(func.count(AuthSession.token_hash))
        .where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None),
               AuthSession.expires_at > datetime.now(timezone.utc)))).scalar_one()
    can_manage = "users.manage" in user.perm_set
    return templates.TemplateResponse(request, "user_form.html", {
        "user": user, "active": "users", "sub": "users", "target": target,
        "roles_map": roles_map, "target_roles": roles_by_user.get(target.id, []),
        "active_sessions": active_sessions,
        "can_manage": can_manage, "saved": bool(saved), "error": error,
        "password_min_len": settings.RANI_PASSWORD_MIN_LEN,
        "is_seed": is_seed_admin(target),
        "is_last_guard": await is_last_guard(session, target.id),
    })


@router.post("/users/{user_id}/update")
async def user_update(user_id: str, request: Request,
                      display_name: str = Form(""), email: str = Form(""),
                      roles: list[str] = Form([]),
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("users.manage"))):
    target = await _load_user_or_404(session, user_id)
    if not roles:
        return RedirectResponse(f"/users/{target.id}?error=pilih+minimal+satu+role",
                                status_code=303)
    before = set((await _user_roles(session, [target.id])).get(target.id, []))
    if target.auth_source == "local":
        target.display_name = display_name.strip()[:128] or None
        target.email = email.strip()[:255] or None
    if await would_lose_last_guard(session, target, roles):
        raise HTTPException(
            status_code=409,
            detail="ditolak: perubahan role ini menghilangkan satu-satunya user aktif "
                   "dengan users.manage + roles.manage (anti-lockout)")
    await _set_user_roles(session, target, roles)
    after = set(roles)
    revoked = 0
    if before != after:
        revoked = await revoke_sessions_for_user(session, target.id)
        await audit(session, request, actor=user.username, action="user.role_change",
                    target=target.username,
                    details={"from": sorted(before), "to": sorted(after),
                             "sessions_revoked": revoked})
    target.updated_at = datetime.now(timezone.utc)
    await audit(session, request, actor=user.username, action="user.update",
                target=target.username,
                details={"display_name": target.display_name, "email": target.email})
    await session.commit()
    return RedirectResponse(f"/users/{target.id}?saved=1", status_code=303)


@router.post("/users/{user_id}/password")
async def user_password_reset(user_id: str, request: Request,
                              password: str = Form(""),
                              session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("users.manage"))):
    target = await _load_user_or_404(session, user_id)
    if target.auth_source != "local":
        raise HTTPException(status_code=400,
                            detail="user AD: password dikelola direktori, bukan RANI")
    error = _check_password(password)
    if error:
        return RedirectResponse(f"/users/{target.id}?error={error[:150]}", status_code=303)
    target.password_hash = hash_password(password)
    target.updated_at = datetime.now(timezone.utc)
    revoked = await revoke_sessions_for_user(session, target.id)
    await audit(session, request, actor=user.username, action="user.password_reset",
                target=target.username, details={"sessions_revoked": revoked})
    await session.commit()
    return RedirectResponse(f"/users/{target.id}?saved=1", status_code=303)


@router.post("/users/{user_id}/active")
async def user_toggle_active(user_id: str, request: Request, active: str = Form("0"),
                             session: AsyncSession = Depends(get_session),
                             user: AppUser = Depends(require_perm("users.manage"))):
    target = await _load_user_or_404(session, user_id)
    enable = active.strip().lower() not in ("", "0", "false", "off", "no")
    if not enable:
        await _guard_disable(session, target)
    target.is_active = enable
    target.updated_at = datetime.now(timezone.utc)
    revoked = 0
    if not enable:
        revoked = await revoke_sessions_for_user(session, target.id)
    await audit(session, request, actor=user.username,
                action="user.enable" if enable else "user.disable",
                target=target.username, details={"sessions_revoked": revoked})
    await session.commit()
    return RedirectResponse(f"/users/{target.id}?saved=1", status_code=303)


@router.post("/users/{user_id}/revoke-sessions")
async def user_revoke_sessions(user_id: str, request: Request,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("users.manage"))):
    target = await _load_user_or_404(session, user_id)
    revoked = await revoke_sessions_for_user(session, target.id)
    await audit(session, request, actor=user.username, action="session.revoke",
                target=target.username, details={"count": revoked})
    await session.commit()
    return RedirectResponse(f"/users/{target.id}?saved=1", status_code=303)


@router.post("/users/{user_id}/delete")
async def user_delete(user_id: str, request: Request,
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("users.manage"))):
    target = await _load_user_or_404(session, user_id)
    await _guard_disable(session, target)
    audit_count = (await session.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.actor == target.username))).scalar_one()
    if audit_count:
        return RedirectResponse(
            f"/users/{target.id}?error=user+memiliki+{audit_count}+jejak+audit;+"
            "nonaktifkan+saja", status_code=303)
    await session.execute(
        AppUserRole.__table__.delete().where(AppUserRole.user_id == target.id))
    await revoke_sessions_for_user(session, target.id)
    await session.delete(target)
    await audit(session, request, actor=user.username, action="user.delete",
                target=target.username)
    await session.commit()
    return RedirectResponse("/users?saved=1", status_code=303)


# ---------------------------------------------------------------- JSON API
class UserIn(BaseModel):
    username: str
    display_name: str | None = None
    email: str | None = None
    password: str
    roles: list[str] = ["reader"]


class UserPatch(BaseModel):
    display_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None


class PasswordIn(BaseModel):
    password: str


class RoleIn(BaseModel):
    slug: str
    name: str
    description: str | None = None
    permissions: list[str] = []


class RolePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


def _user_json(u: AppUser, roles: list[str]) -> dict:
    return {"id": str(u.id), "username": u.username, "display_name": u.display_name,
            "email": u.email, "auth_source": u.auth_source, "domain": u.domain,
            "upn": u.upn, "is_active": u.is_active, "roles": roles,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}


def _role_json(r: Role) -> dict:
    return {"id": str(r.id), "slug": r.slug, "name": r.name,
            "description": r.description, "permissions": r.permissions or [],
            "is_builtin": r.is_builtin}


@api_router.get("/permissions")
async def api_permissions(user: AppUser = Depends(require_perm("roles.view"))) -> dict:
    return {"permissions": [{"key": k, "description": v} for k, v in PERMISSIONS.items()]}


@api_router.get("/users")
async def api_users_list(q: str | None = None, source: str | None = None,
                         status: str | None = None, role: str | None = None,
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("users.view"))) -> dict:
    stmt = select(AppUser).order_by(AppUser.username)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(AppUser.username.ilike(like) | AppUser.display_name.ilike(like))
    if source in ("local", "ad"):
        stmt = stmt.where(AppUser.auth_source == source)
    if status == "active":
        stmt = stmt.where(AppUser.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(AppUser.is_active.is_(False))
    rows = (await session.execute(stmt)).scalars().all()
    roles_by_user = await _user_roles(session, [u.id for u in rows])
    if role:
        rows = [u for u in rows if role in roles_by_user.get(u.id, [])]
    return {"items": [_user_json(u, roles_by_user.get(u.id, [])) for u in rows]}


@api_router.post("/users", status_code=201)
async def api_users_create(body: UserIn, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("users.manage"))) -> dict:
    username = _local_username(body.username)
    error = _validate_local_username(username) or _check_password(body.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if not body.roles:
        raise HTTPException(status_code=400, detail="minimal satu role")
    new_user = AppUser(username=username,
                       display_name=(body.display_name or "").strip()[:128] or None,
                       email=(body.email or "").strip()[:255] or None,
                       password_hash=hash_password(body.password), auth_source="local")
    session.add(new_user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="username sudah dipakai") from None
    await _set_user_roles(session, new_user, body.roles)
    await audit(session, request, actor=user.username, action="user.create",
                target=username, details={"roles": body.roles, "via": "api"})
    await session.commit()
    return _user_json(new_user, body.roles)


@api_router.patch("/users/{user_id}")
async def api_users_patch(user_id: str, body: UserPatch, request: Request,
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("users.manage"))) -> dict:
    target = await _load_user_or_404(session, user_id)
    if body.display_name is not None and target.auth_source == "local":
        target.display_name = body.display_name.strip()[:128] or None
    if body.email is not None and target.auth_source == "local":
        target.email = body.email.strip()[:255] or None
    before = set((await _user_roles(session, [target.id])).get(target.id, []))
    if body.roles is not None:
        if not body.roles:
            raise HTTPException(status_code=400, detail="minimal satu role")
        if await would_lose_last_guard(session, target, body.roles):
            raise HTTPException(status_code=409,
                                detail="menghilangkan user guard terakhir (anti-lockout)")
        await _set_user_roles(session, target, body.roles)
        if before != set(body.roles):
            revoked = await revoke_sessions_for_user(session, target.id)
            await audit(session, request, actor=user.username, action="user.role_change",
                        target=target.username,
                        details={"from": sorted(before), "to": sorted(body.roles),
                                 "sessions_revoked": revoked})
    if body.is_active is not None:
        if not body.is_active:
            await _guard_disable(session, target)
        target.is_active = body.is_active
        if not body.is_active:
            revoked = await revoke_sessions_for_user(session, target.id)
        await audit(session, request, actor=user.username,
                    action="user.enable" if body.is_active else "user.disable",
                    target=target.username)
    target.updated_at = datetime.now(timezone.utc)
    await session.commit()
    roles = (await _user_roles(session, [target.id])).get(target.id, [])
    return _user_json(target, roles)


@api_router.post("/users/{user_id}/password")
async def api_users_password(user_id: str, body: PasswordIn, request: Request,
                             session: AsyncSession = Depends(get_session),
                             user: AppUser = Depends(require_perm("users.manage"))) -> dict:
    target = await _load_user_or_404(session, user_id)
    if target.auth_source != "local":
        raise HTTPException(status_code=400, detail="user AD: password dikelola AD")
    error = _check_password(body.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    target.password_hash = hash_password(body.password)
    target.updated_at = datetime.now(timezone.utc)
    revoked = await revoke_sessions_for_user(session, target.id)
    await audit(session, request, actor=user.username, action="user.password_reset",
                target=target.username, details={"sessions_revoked": revoked, "via": "api"})
    await session.commit()
    return {"ok": True, "sessions_revoked": revoked}


@api_router.post("/users/{user_id}/revoke-sessions")
async def api_users_revoke(user_id: str, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("users.manage"))) -> dict:
    target = await _load_user_or_404(session, user_id)
    revoked = await revoke_sessions_for_user(session, target.id)
    await audit(session, request, actor=user.username, action="session.revoke",
                target=target.username, details={"count": revoked, "via": "api"})
    await session.commit()
    return {"ok": True, "sessions_revoked": revoked}


@api_router.get("/roles")
async def api_roles_list(session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("roles.view"))) -> dict:
    roles = (await session.execute(select(Role).order_by(Role.slug))).scalars().all()
    counts = await _role_user_counts(session)
    return {"items": [{**_role_json(r), "users": counts.get(r.id, 0)} for r in roles]}


@api_router.post("/roles", status_code=201)
async def api_roles_create(body: RoleIn, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("roles.manage"))) -> dict:
    slug = (body.slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="slug tidak valid")
    if slug in {r["slug"] for r in DEFAULT_ROLES}:
        raise HTTPException(status_code=400, detail="slug direservasi role bawaan")
    role = Role(slug=slug, name=body.name.strip()[:MAX_NAME],
                description=(body.description or "").strip()[:500] or None,
                permissions=normalize_permissions(body.permissions), is_builtin=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc))
    session.add(role)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="slug sudah dipakai") from None
    await audit(session, request, actor=user.username, action="role.create",
                target=slug, details={"via": "api"})
    await session.commit()
    return _role_json(role)


@api_router.patch("/roles/{role_id}")
async def api_roles_patch(role_id: str, body: RolePatch, request: Request,
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("roles.manage"))) -> dict:
    role = await _load_role_or_404(session, role_id)
    if role.slug == "admin":
        raise HTTPException(status_code=403, detail="role admin terkunci")
    if body.name is not None:
        role.name = body.name.strip()[:MAX_NAME] or role.name
    if body.description is not None:
        role.description = body.description.strip()[:500] or None
    if body.permissions is not None:
        role.permissions = normalize_permissions(body.permissions)
        role.updated_at = datetime.now(timezone.utc)
        await session.flush()
        if await count_guard_capable(session) == 0:
            raise HTTPException(status_code=409,
                                detail="menghilangkan user guard terakhir (anti-lockout)")
    role.updated_at = datetime.now(timezone.utc)
    await audit(session, request, actor=user.username, action="role.update",
                target=role.slug, details={"via": "api"})
    await session.commit()
    return _role_json(role)


@api_router.delete("/roles/{role_id}")
async def api_roles_delete(role_id: str, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("roles.manage"))) -> dict:
    role = await _load_role_or_404(session, role_id)
    if role.is_builtin:
        raise HTTPException(status_code=403, detail="role bawaan tidak bisa dihapus")
    users_count = (await session.execute(
        select(func.count(AppUserRole.user_id))
        .where(AppUserRole.role_id == role.id))).scalar_one()
    if users_count:
        raise HTTPException(status_code=409,
                            detail=f"role masih dipakai {users_count} user")
    mappings = (await session.execute(
        select(func.count(DirectoryGroupRole.id))
        .where(DirectoryGroupRole.role_id == role.id))).scalar_one()
    if mappings:
        raise HTTPException(status_code=409,
                            detail=f"role masih dipakai {mappings} mapping group AD")
    await session.delete(role)
    await audit(session, request, actor=user.username, action="role.delete",
                target=role.slug, details={"via": "api"})
    await session.commit()
    return {"ok": True}
