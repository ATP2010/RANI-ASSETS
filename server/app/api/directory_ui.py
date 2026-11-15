"""Menu Users → Direktori (AD): connector LDAP/LDAPS (F5.4), mapping group → role
dan sync (F5.5). JSON API /api/v1/directory. Operasi LDAP dijalankan di threadpool.
"""
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import directory as ad
from app.adsync import sync_connector
from app.audit import audit
from app.config import get_settings
from app.db import get_session
from app.deps import require_perm
from app.models import (AppUser, DirectoryConnector, DirectoryGroupRole,
                        DirectorySyncRun, Role)
from app.templating import templates

log = logging.getLogger("rani.directory.ui")
router = APIRouter(include_in_schema=False)
api_router = APIRouter(prefix="/api/v1/directory", tags=["directory"])
settings = get_settings()

MAX = 255


def _now():
    return datetime.now(timezone.utc)


async def _load_connector_or_404(session: AsyncSession, connector_id: str) -> DirectoryConnector:
    try:
        parsed = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="connector tidak ditemukan") from None
    row = await session.get(DirectoryConnector, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="connector tidak ditemukan")
    return row


async def _roles(session: AsyncSession) -> list[Role]:
    return list((await session.execute(select(Role).order_by(Role.slug))).scalars().all())


async def _mappings(session: AsyncSession, connector_id) -> list[dict]:
    rows = (await session.execute(
        select(DirectoryGroupRole, Role.name, Role.slug)
        .join(Role, Role.id == DirectoryGroupRole.role_id)
        .where(DirectoryGroupRole.connector_id == connector_id)
        .order_by(DirectoryGroupRole.group_name))).all()
    return [{"mapping": m, "role_name": rn, "role_slug": rs} for m, rn, rs in rows]


async def _runs(session: AsyncSession, connector_id, limit: int = 10) -> list[DirectorySyncRun]:
    return list((await session.execute(
        select(DirectorySyncRun).where(DirectorySyncRun.connector_id == connector_id)
        .order_by(DirectorySyncRun.started_at.desc()).limit(limit))).scalars().all())


def _connector_dict(c: DirectoryConnector) -> dict:
    return {"id": str(c.id), "name": c.name, "domain": c.domain,
            "domain_fqdn": c.domain_fqdn, "url": c.url, "use_ldaps": c.use_ldaps,
            "tls_verify": c.tls_verify, "base_dn": c.base_dn,
            "user_filter": c.user_filter, "group_filter": c.group_filter,
            "nested_groups": c.nested_groups, "sync_interval_s": c.sync_interval_s,
            "enabled": c.enabled, "has_bind_password": bool(c.bind_password_enc),
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "last_sync_status": c.last_sync_status, "last_sync_error": c.last_sync_error}


# ---------------------------------------------------------------- UI
@router.get("/users/directory")
async def directory_page(request: Request, id: str | None = None, q: str | None = None,
                         saved: int = 0, error: str | None = None,
                         test_ok: int | None = None, test_msg: str | None = None,
                         sync_msg: str | None = None,
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("directory.view"))):
    connectors = list((await session.execute(
        select(DirectoryConnector).order_by(DirectoryConnector.name))).scalars().all())
    creating = id == "new"
    selected = None
    if id and not creating:
        selected = next((c for c in connectors if str(c.id) == id), None)
    elif not id and connectors:
        selected = connectors[0]

    groups: list[dict] = []
    groups_error = None
    mappings: list[dict] = []
    runs: list[DirectorySyncRun] = []
    if selected is not None:
        mappings = await _mappings(session, selected.id)
        runs = await _runs(session, selected.id)
        if q is not None:
            try:
                groups = await run_in_threadpool(ad.browse_groups, selected,
                                                 q.strip() or None, 50)
            except Exception as exc:  # noqa: BLE001
                groups_error = str(exc)[:300]

    can_manage = "directory.manage" in user.perm_set
    can_sync = "directory.sync" in user.perm_set or can_manage
    return templates.TemplateResponse(request, "directory.html", {
        "user": user, "active": "users", "sub": "directory",
        "connectors": connectors, "selected": selected,
        "mappings": mappings, "runs": runs,
        "groups": groups, "q": q if q is not None else None,
        "groups_error": groups_error,
        "saved": bool(saved), "error": error,
        "test_ok": test_ok, "test_msg": test_msg, "sync_msg": sync_msg,
        "can_manage": can_manage, "can_sync": can_sync,
        "roles": await _roles(session),
        "default_user_filter": ad.default_user_filter(),
        "default_sync_interval_s": settings.RANI_AD_SYNC_INTERVAL_S,
        "creating": creating,
        "ad_login_enabled": settings.RANI_AD_ENABLED,
        "auth_local_enabled": settings.RANI_AUTH_LOCAL_ENABLED,
    })


def _form_connector_values(form: dict) -> dict:
    return form


@router.post("/users/directory")
async def directory_save(request: Request,
                         connector_id: str = Form(""),
                         name: str = Form(""), domain: str = Form(""),
                         domain_fqdn: str = Form(""), url: str = Form(""),
                         use_ldaps: str = Form(""), tls_verify: str = Form(""),
                         ca_cert_pem: str = Form(""),
                         bind_dn: str = Form(""), bind_password: str = Form(""),
                         base_dn: str = Form(""),
                         user_filter: str = Form(""), group_filter: str = Form(""),
                         nested_groups: str = Form(""),
                         sync_interval_s: int = Form(3600),
                         enabled: str = Form(""),
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("directory.manage"))):
    name = name.strip()[:96]
    domain = domain.strip().lower()[:64]
    fqdn = domain_fqdn.strip().lower()[:255]
    url = url.strip()[:255]
    error = None
    if not name:
        error = "nama connector wajib diisi"
    elif not domain or not all(ch.isalnum() or ch in "-." for ch in domain):
        error = "domain NetBIOS tidak valid (huruf/angka), mis. CORP"
    elif not fqdn or "." not in fqdn:
        error = "domain FQDN tidak valid, mis. corp.local"
    elif not (url.startswith("ldap://") or url.startswith("ldaps://")):
        error = "URL harus diawali ldap:// atau ldaps://"
    elif not bind_dn.strip():
        error = "bind DN wajib diisi"
    elif not base_dn.strip():
        error = "base DN wajib diisi"
    if error:
        return RedirectResponse(f"/users/directory?error={quote(error)}", status_code=303)

    target: DirectoryConnector | None = None
    if connector_id:
        target = await _load_connector_or_404(session, connector_id)
    creating = target is None
    if target is None:
        target = DirectoryConnector(created_at=_now(), updated_at=_now())
        session.add(target)

    target.name = name
    target.domain = domain.upper()
    target.domain_fqdn = fqdn
    target.url = url
    target.use_ldaps = use_ldaps.strip().lower() not in ("", "0", "false", "off", "no")
    target.tls_verify = tls_verify.strip().lower() not in ("", "0", "false", "off", "no")
    target.ca_cert_pem = ca_cert_pem.strip() or None
    target.bind_dn = bind_dn.strip()[:MAX]
    if bind_password.strip():
        target.bind_password_enc = ad.encrypt_bind_password(bind_password.strip())
    elif creating and not target.bind_password_enc:
        return RedirectResponse(
            f"/users/directory?error={quote('bind password wajib diisi untuk connector baru')}",
            status_code=303)
    target.base_dn = base_dn.strip()[:MAX]
    target.user_filter = user_filter.strip() or ad.default_user_filter()
    target.group_filter = group_filter.strip() or "(objectClass=group)"
    target.nested_groups = nested_groups.strip().lower() not in ("", "0", "false", "off", "no")
    target.sync_interval_s = max(0, int(sync_interval_s or 0))
    target.enabled = enabled.strip().lower() not in ("", "0", "false", "off", "no")
    target.updated_at = _now()
    await session.flush()
    await audit(session, request, actor=user.username,
                action="ad.connector.create" if creating else "ad.connector.update",
                target=target.name,
                details={"domain": target.domain, "url": target.url,
                         "use_ldaps": target.use_ldaps, "tls_verify": target.tls_verify,
                         "sync_interval_s": target.sync_interval_s,
                         "nested_groups": target.nested_groups,
                         "bind_password_set": bool(bind_password.strip())})
    await session.commit()
    return RedirectResponse(f"/users/directory?id={target.id}&saved=1", status_code=303)


@router.post("/users/directory/{connector_id}/delete")
async def directory_delete(connector_id: str, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("directory.manage"))):
    target = await _load_connector_or_404(session, connector_id)
    ad_count = (await session.execute(
        select(func.count(AppUser.id))
        .where(AppUser.auth_source == "ad", AppUser.domain == target.domain,
               AppUser.is_active.is_(True)))).scalar_one()
    name = target.name
    await session.delete(target)  # mappings + sync runs ikut terhapus (cascade)
    await audit(session, request, actor=user.username,
                action="ad.connector.delete", target=name,
                details={"active_ad_users": ad_count})
    await session.commit()
    return RedirectResponse("/users/directory?saved=1", status_code=303)


@router.post("/users/directory/{connector_id}/test")
async def directory_test(connector_id: str, request: Request,
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("directory.manage"))):
    target = await _load_connector_or_404(session, connector_id)
    result = await run_in_threadpool(ad.test_connection, target)
    await audit(session, request, actor=user.username, action="ad.connector.test",
                target=target.name,
                outcome="success" if result["ok"] else "failure",
                details={"error": result["error"], "users": result["users"],
                         "groups": result["groups"]})
    await session.commit()
    if result["ok"]:
        msg = f"OK — bind dan baca rootDSE berhasil. User: {result['users']}, grup: {result['groups']}"
        return RedirectResponse(f"/users/directory?id={target.id}&test_ok=1&test_msg={quote(msg)}",
                                status_code=303)
    return RedirectResponse(f"/users/directory?id={target.id}&test_ok=0&test_msg={quote(result['error'])}",
                            status_code=303)


@router.post("/users/directory/{connector_id}/map")
async def directory_map_group(connector_id: str, request: Request,
                              group_dn: str = Form(""), group_name: str = Form(""),
                              role_id: str = Form(""),
                              session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("directory.manage"))):
    target = await _load_connector_or_404(session, connector_id)
    group_dn = group_dn.strip()[:512]
    group_name = group_name.strip()[:255] or group_dn
    try:
        parsed_role = uuid.UUID(role_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="role tidak valid") from None
    role = await session.get(Role, parsed_role)
    if role is None:
        raise HTTPException(status_code=400, detail="role tidak ditemukan")
    if not group_dn:
        raise HTTPException(status_code=400, detail="group DN wajib diisi")
    session.add(DirectoryGroupRole(connector_id=target.id, group_dn=group_dn,
                                   group_name=group_name, role_id=role.id, enabled=True))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return RedirectResponse(
            f"/users/directory?id={target.id}&error={quote('group itu sudah dipetakan')}",
            status_code=303)
    await audit(session, request, actor=user.username, action="ad.group_role.map",
                target=target.name,
                details={"group": group_dn, "role": role.slug})
    await session.commit()
    return RedirectResponse(f"/users/directory?id={target.id}&saved=1", status_code=303)


@router.post("/users/directory/mapping/{mapping_id}/delete")
async def directory_unmap_group(mapping_id: str, request: Request,
                                session: AsyncSession = Depends(get_session),
                                user: AppUser = Depends(require_perm("directory.manage"))):
    try:
        parsed = uuid.UUID(mapping_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="mapping tidak ditemukan") from None
    mapping = await session.get(DirectoryGroupRole, parsed)
    if mapping is None:
        raise HTTPException(status_code=404, detail="mapping tidak ditemukan")
    connector_id = str(mapping.connector_id)
    await session.delete(mapping)
    await audit(session, request, actor=user.username, action="ad.group_role.unmap",
                target=mapping.group_dn)
    await session.commit()
    return RedirectResponse(f"/users/directory?id={connector_id}&saved=1", status_code=303)


@router.post("/users/directory/{connector_id}/sync")
async def directory_sync(connector_id: str, request: Request,
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("directory.sync"))):
    target = await _load_connector_or_404(session, connector_id)
    summary = await sync_connector(session, target, mode="manual", actor=user.username)
    msg = (f"sync {summary['status']}: {summary['users_seen']} user, "
           f"+{summary['created']} baru, {summary['updated']} diperbarui, "
           f"{summary['deactivated']} dinonaktifkan")
    if summary.get("error"):
        msg += f" — {summary['error'][:150]}"
    return RedirectResponse(f"/users/directory?id={target.id}&sync_msg={quote(msg)}",
                            status_code=303)


# ---------------------------------------------------------------- JSON API
class ConnectorIn(BaseModel):
    name: str
    domain: str
    domain_fqdn: str
    url: str
    use_ldaps: bool = True
    tls_verify: bool = True
    ca_cert_pem: str | None = None
    bind_dn: str
    bind_password: str
    base_dn: str
    user_filter: str | None = None
    group_filter: str | None = None
    nested_groups: bool = False
    sync_interval_s: int = 3600
    enabled: bool = True


class ConnectorPatch(BaseModel):
    name: str | None = None
    domain: str | None = None
    domain_fqdn: str | None = None
    url: str | None = None
    use_ldaps: bool | None = None
    tls_verify: bool | None = None
    ca_cert_pem: str | None = None
    bind_dn: str | None = None
    bind_password: str | None = None
    base_dn: str | None = None
    user_filter: str | None = None
    group_filter: str | None = None
    nested_groups: bool | None = None
    sync_interval_s: int | None = None
    enabled: bool | None = None


class GroupRoleIn(BaseModel):
    connector_id: str
    group_dn: str
    group_name: str | None = None
    role_id: str
    enabled: bool = True


@api_router.get("/connectors")
async def api_connectors_list(session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("directory.view"))) -> dict:
    rows = (await session.execute(
        select(DirectoryConnector).order_by(DirectoryConnector.name))).scalars().all()
    return {"items": [_connector_dict(c) for c in rows]}


@api_router.post("/connectors", status_code=201)
async def api_connectors_create(body: ConnectorIn, request: Request,
                                session: AsyncSession = Depends(get_session),
                                user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    conn = DirectoryConnector(
        name=body.name.strip()[:96], domain=body.domain.strip().upper()[:64],
        domain_fqdn=body.domain_fqdn.strip().lower()[:255], url=body.url.strip()[:255],
        use_ldaps=body.use_ldaps, tls_verify=body.tls_verify,
        ca_cert_pem=(body.ca_cert_pem or "").strip() or None,
        bind_dn=body.bind_dn.strip()[:MAX],
        bind_password_enc=ad.encrypt_bind_password(body.bind_password),
        base_dn=body.base_dn.strip()[:MAX],
        user_filter=(body.user_filter or ad.default_user_filter()).strip(),
        group_filter=(body.group_filter or "(objectClass=group)").strip(),
        nested_groups=body.nested_groups,
        sync_interval_s=max(0, body.sync_interval_s),
        enabled=body.enabled, created_at=_now(), updated_at=_now())
    session.add(conn)
    await session.flush()
    await audit(session, request, actor=user.username, action="ad.connector.create",
                target=conn.name, details={"via": "api"})
    await session.commit()
    return _connector_dict(conn)


@api_router.patch("/connectors/{connector_id}")
async def api_connectors_patch(connector_id: str, body: ConnectorPatch, request: Request,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    data = body.model_dump(exclude_unset=True)
    if "bind_password" in data:
        plain = (data.pop("bind_password") or "").strip()
        if plain:
            conn.bind_password_enc = ad.encrypt_bind_password(plain)
    for key, value in data.items():
        setattr(conn, key, value)
    conn.updated_at = _now()
    await audit(session, request, actor=user.username, action="ad.connector.update",
                target=conn.name, details={"via": "api", "fields": sorted(data)})
    await session.commit()
    return _connector_dict(conn)


@api_router.delete("/connectors/{connector_id}")
async def api_connectors_delete(connector_id: str, request: Request,
                                session: AsyncSession = Depends(get_session),
                                user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    name = conn.name
    await session.delete(conn)
    await audit(session, request, actor=user.username, action="ad.connector.delete",
                target=name, details={"via": "api"})
    await session.commit()
    return {"ok": True}


@api_router.post("/connectors/{connector_id}/test")
async def api_connectors_test(connector_id: str, request: Request,
                              session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    result = await run_in_threadpool(ad.test_connection, conn)
    await audit(session, request, actor=user.username, action="ad.connector.test",
                target=conn.name,
                outcome="success" if result["ok"] else "failure",
                details={"error": result["error"], "via": "api"})
    await session.commit()
    return result


@api_router.get("/connectors/{connector_id}/groups")
async def api_connectors_groups(connector_id: str, q: str | None = None,
                                session: AsyncSession = Depends(get_session),
                                user: AppUser = Depends(require_perm("directory.view"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    try:
        groups = await run_in_threadpool(ad.browse_groups, conn, q or None, 100)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    return {"items": groups}


@api_router.post("/connectors/{connector_id}/sync")
async def api_connectors_sync(connector_id: str, request: Request,
                              session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("directory.sync"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    return await sync_connector(session, conn, mode="manual", actor=user.username)


@api_router.get("/connectors/{connector_id}/sync-runs")
async def api_connectors_runs(connector_id: str, limit: int = Query(20, ge=1, le=200),
                              session: AsyncSession = Depends(get_session),
                              user: AppUser = Depends(require_perm("directory.view"))) -> dict:
    conn = await _load_connector_or_404(session, connector_id)
    rows = await _runs(session, conn.id, limit)
    return {"items": [{
        "run_id": str(r.id), "mode": r.mode, "status": r.status,
        "users_seen": r.users_seen, "created": r.created, "updated": r.updated,
        "deactivated": r.deactivated, "roles_changed": r.roles_changed,
        "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    } for r in rows]}


@api_router.get("/group-roles")
async def api_group_roles_list(connector_id: str | None = None,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("directory.view"))) -> dict:
    stmt = select(DirectoryGroupRole, Role.slug).join(Role, Role.id == DirectoryGroupRole.role_id)
    if connector_id:
        stmt = stmt.where(DirectoryGroupRole.connector_id == uuid.UUID(connector_id))
    rows = (await session.execute(stmt.order_by(DirectoryGroupRole.group_name))).all()
    return {"items": [{"id": str(m.id), "connector_id": str(m.connector_id),
                       "group_dn": m.group_dn, "group_name": m.group_name,
                       "role_id": str(m.role_id), "role_slug": slug,
                       "enabled": m.enabled} for m, slug in rows]}


@api_router.post("/group-roles", status_code=201)
async def api_group_roles_create(body: GroupRoleIn, request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    conn = await _load_connector_or_404(session, body.connector_id)
    try:
        role = await session.get(Role, uuid.UUID(body.role_id))
    except ValueError:
        role = None
    if role is None:
        raise HTTPException(status_code=400, detail="role tidak ditemukan")
    mapping = DirectoryGroupRole(connector_id=conn.id,
                                 group_dn=body.group_dn.strip()[:512],
                                 group_name=(body.group_name or body.group_dn).strip()[:255],
                                 role_id=role.id, enabled=body.enabled)
    session.add(mapping)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="group itu sudah dipetakan") from None
    await audit(session, request, actor=user.username, action="ad.group_role.map",
                target=conn.name,
                details={"group": mapping.group_dn, "role": role.slug, "via": "api"})
    await session.commit()
    return {"id": str(mapping.id)}


@api_router.delete("/group-roles/{mapping_id}")
async def api_group_roles_delete(mapping_id: str, request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 user: AppUser = Depends(require_perm("directory.manage"))) -> dict:
    try:
        parsed = uuid.UUID(mapping_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="mapping tidak ditemukan") from None
    mapping = await session.get(DirectoryGroupRole, parsed)
    if mapping is None:
        raise HTTPException(status_code=404, detail="mapping tidak ditemukan")
    await session.delete(mapping)
    await audit(session, request, actor=user.username, action="ad.group_role.unmap",
                target=mapping.group_dn, details={"via": "api"})
    await session.commit()
    return {"ok": True}
