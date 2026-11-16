"""Menu Agents (submenu): Push (agent + tutorial + unduhan) dan Scan (SNMP + grup IP)."""
import logging
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.downloads import ARTIFACTS, artifact_sha256
from app.audit import audit
from app.config import get_settings
from app.crypto import encrypt_secret
from app.db import get_session
from app.deps import require_perm, require_user
from app.models import AppUser, ScanGroup, ScanOid, ScanResult, ScanRun
from app.queries import list_agents, list_port_map, list_tokens, port_map_summary
from app.scanner import ScanError, expand_hosts, normalize_range, parse_ranges, running_for
from app.templating import templates

log = logging.getLogger("rani.agents.ui")
router = APIRouter(include_in_schema=False)
settings = get_settings()

MAX_NAME = 128
MAX_DESC = 2000


def _group_stats(group: ScanGroup) -> dict:
    try:
        hosts, truncated = expand_hosts(group.ranges or [], settings.RANI_SCAN_MAX_HOSTS)
        return {"hosts": len(hosts), "truncated": truncated}
    except Exception:  # noqa: BLE001 — data lama bisa saja tidak valid
        return {"hosts": 0, "truncated": False}


DOCS = {
    "agent-windows": "agent-windows.md",
    "scan": "scan.md",
    "users": "users.md",
    "actions": "actions.md",
    "reports": "reports.md",
    "branding": "branding.md",
    "deploy-dockerhub": "deploy-dockerhub.md",
    "dockerhub-overview": "dockerhub-overview.md",
    "deploy-caddy": "deploy-caddy.md",
    "analysis": "analysis.md",
    "overview": "overview.md",
}


@router.get("/docs/{slug}")
async def docs_view(slug: str, request: Request,
                    user: AppUser = Depends(require_user())):
    name = DOCS.get(slug)
    if name is None:
        raise HTTPException(status_code=404, detail="dokumen tidak ditemukan")
    path = Path(settings.RANI_DOCS_DIR) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} belum tersedia di image")
    return templates.TemplateResponse(request, "docs_view.html", {
        "user": user, "active": "", "sub": "", "title": name,
        "body": path.read_text(encoding="utf-8", errors="replace"),
    })


@router.get("/agents")
async def agents_root():
    return RedirectResponse("/agents/push", status_code=307)


@router.get("/agents/push")
async def agents_push(request: Request, token: str | None = None,
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("agents.view"))):
    signed_name = "raniPush-signed.exe"
    signed_label = ARTIFACTS[signed_name][0]
    path = Path(settings.RANI_AGENT_DIR) / signed_name
    size = path.stat().st_size if path.is_file() else None

    def _art(name: str) -> dict:
        p = Path(settings.RANI_AGENT_DIR if ARTIFACTS[name][1] == "release"
                 else settings.RANI_AGENT_SCRIPTS_DIR) / name
        sz = p.stat().st_size if p.is_file() else None
        return {"name": name, "label": ARTIFACTS[name][0], "size": sz,
                "size_mb": round(sz / 1048576, 2) if sz else None,
                "available": sz is not None, "sha256": artifact_sha256(name)}

    return templates.TemplateResponse(request, "agents_push.html", {
        "user": user, "active": "agents", "sub": "push",
        "agents": await list_agents(session), "tokens": await list_tokens(session),
        "new_token": token, "exe": {"name": signed_name, "label": signed_label,
                                    "size": size,
                                    "size_mb": round(size / 1048576, 2) if size else None,
                                    "available": size is not None},
        "portable": _art("raniPush-portable.zip"),
        "signed": _art("raniPush-signed.exe"),
        "plain": _art("raniPush.exe"),
        "cert": _art("rani-push-signing.cer"),
        "server_url": str(request.base_url).rstrip("/"),
        "server_host": urlsplit(str(request.base_url)).hostname or "127.0.0.1",
        "server_port": urlsplit(str(request.base_url)).port or 8091,
        "can_admin": "agents.manage" in getattr(user, "perm_set", set()),
    })


@router.get("/agents/scan")
async def agents_scan(request: Request, run: str | None = None,
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("scan.view"))):
    groups = (await session.execute(
        select(ScanGroup).order_by(ScanGroup.name))).scalars().all()
    history = (await session.execute(
        select(ScanRun, ScanGroup.name)
        .outerjoin(ScanGroup, ScanGroup.id == ScanRun.group_id)
        .order_by(ScanRun.started_at.desc()).limit(15))).all()
    selected = None
    results = []
    if run:
        try:
            run_id = uuid.UUID(run)
        except ValueError:
            run_id = None
        if run_id:
            selected = (await session.execute(
                select(ScanRun).where(ScanRun.id == run_id))).scalar_one_or_none()
            if selected:
                results = (await session.execute(
                    select(ScanResult).where(ScanResult.run_id == run_id)
                    .order_by(ScanResult.status, ScanResult.ip).limit(500))).scalars().all()
    if selected is None:
        selected = history[0][0] if history else None
        if selected:
            results = (await session.execute(
                select(ScanResult).where(ScanResult.run_id == selected.id)
                .order_by(ScanResult.status, ScanResult.ip).limit(500))).scalars().all()
    oids = (await session.execute(
        select(ScanOid).order_by(ScanOid.label))).scalars().all()
    return templates.TemplateResponse(request, "scan.html", {
        "user": user, "active": "agents", "sub": "scan",
        "groups": [{"group": g, "stats": _group_stats(g),
                    "running": running_for(g.id)} for g in groups],
        "history": [{"run": r, "group_name": name} for r, name in history],
        "selected": selected, "results": results, "oids": oids,
        "can_run": "scan.run" in getattr(user, "perm_set", set()),
        "max_hosts": settings.RANI_SCAN_MAX_HOSTS,
        "timeout_s": settings.RANI_SCAN_TIMEOUT_S,
        "concurrency": settings.RANI_SCAN_CONCURRENCY,
    })


@router.get("/agents/portmap")
async def agents_portmap(request: Request, switch: str | None = None, q: str | None = None,
                         stale: int = 0,
                         session: AsyncSession = Depends(get_session),
                         user: AppUser = Depends(require_perm("portmap.view"))):
    """Port map L2: MAC terlihat di port switch mana (hasil bridge FDB)."""
    switch_id = None
    if switch:
        try:
            switch_id = uuid.UUID(switch)
        except ValueError:
            switch_id = None
    rows = await list_port_map(session, switch_id=switch_id, q=q,
                               present_only=not bool(stale), limit=2000)
    per_port: dict[str, int] = {}
    for row in rows:
        name = row["mapping"].if_name or "(tanpa nama port)"
        per_port[name] = per_port.get(name, 0) + 1
    return templates.TemplateResponse(request, "portmap.html", {
        "user": user, "active": "agents", "sub": "portmap",
        "summary": await port_map_summary(session), "rows": rows,
        "q": q or "", "switch": switch or "", "stale": bool(stale),
        "per_port": per_port,
        "uplink_min": settings.RANI_SCAN_FDB_UPLINK_MACS,
        "fdb_max": settings.RANI_SCAN_FDB_MAX,
    })


@router.get("/agents/groups")
async def scan_groups_page(request: Request, edit: str | None = None,
                           oid_error: str | None = None,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("scan.view"))):
    groups = (await session.execute(
        select(ScanGroup).order_by(ScanGroup.name))).scalars().all()
    oids = (await session.execute(
        select(ScanOid).order_by(ScanOid.label))).scalars().all()
    editing = None
    if edit:
        try:
            editing = (await session.execute(
                select(ScanGroup).where(ScanGroup.id == uuid.UUID(edit)))).scalar_one_or_none()
        except ValueError:
            editing = None
    return templates.TemplateResponse(request, "scan_groups.html", {
        "user": user, "active": "agents", "sub": "groups",
        "groups": [{"group": g, "stats": _group_stats(g)} for g in groups],
        "oids": oids, "editing": editing, "error": None, "values": {},
        "oid_error": oid_error,
        "can_manage": "scan.manage" in getattr(user, "perm_set", set()),
        "max_hosts": settings.RANI_SCAN_MAX_HOSTS,
    })


def _form_values(name: str, description: str, ranges: str, snmp_version: str,
                 port: str, fdb_enabled: bool = True) -> dict:
    return {"name": name, "description": description, "ranges": ranges,
            "snmp_version": snmp_version, "port": port, "fdb_enabled": fdb_enabled}


@router.post("/agents/groups/save")
async def scan_group_save(request: Request, group_id: str = Form(""),
                          name: str = Form(""), description: str = Form(""),
                          ranges: str = Form(""), snmp_version: str = Form("2c"),
                          community: str = Form(""), port: str = Form("161"),
                          fdb_enabled: str = Form(""),
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("scan.manage"))):
    error = None
    parsed_ranges: list[str] = []
    port_num = 161
    clean_name = name.strip()[:MAX_NAME]
    fdb_on = fdb_enabled.strip().lower() not in ("", "0", "false", "off", "no")
    try:
        if not clean_name:
            raise ScanError("nama grup wajib diisi")
        parsed_ranges = parse_ranges(ranges.splitlines())
        port_num = int(port or 161)
        if not (1 <= port_num <= 65535):
            raise ScanError("port SNMP harus 1..65535")
    except (ScanError, ValueError) as exc:
        error = str(exc)
    if snmp_version not in ("1", "2c"):
        error = error or "versi SNMP harus 1 atau 2c"

    target = None
    if group_id:
        try:
            target = (await session.execute(
                select(ScanGroup).where(ScanGroup.id == uuid.UUID(group_id)))).scalar_one_or_none()
        except ValueError:
            target = None
        if target is None:
            raise HTTPException(status_code=404, detail="grup tidak ditemukan")

    if error:
        groups = (await session.execute(
            select(ScanGroup).order_by(ScanGroup.name))).scalars().all()
        oids = (await session.execute(
            select(ScanOid).order_by(ScanOid.label))).scalars().all()
        return templates.TemplateResponse(request, "scan_groups.html", {
            "user": user, "active": "agents", "sub": "groups",
            "groups": [{"group": g, "stats": _group_stats(g)} for g in groups],
            "oids": oids, "editing": target, "error": error,
            "values": _form_values(name, description, ranges, snmp_version, port, fdb_on),
            "can_manage": True, "max_hosts": settings.RANI_SCAN_MAX_HOSTS,
        }, status_code=400)

    if target is None and not community.strip():
        error = error or "community SNMP wajib diisi untuk grup baru"

    if error:
        groups = (await session.execute(
            select(ScanGroup).order_by(ScanGroup.name))).scalars().all()
        oids = (await session.execute(
            select(ScanOid).order_by(ScanOid.label))).scalars().all()
        return templates.TemplateResponse(request, "scan_groups.html", {
            "user": user, "active": "agents", "sub": "groups",
            "groups": [{"group": g, "stats": _group_stats(g)} for g in groups],
            "oids": oids, "editing": target, "error": error,
            "values": _form_values(name, description, ranges, snmp_version, port, fdb_on),
            "can_manage": True, "max_hosts": settings.RANI_SCAN_MAX_HOSTS,
        }, status_code=400)

    if target is None:
        target = ScanGroup(name=clean_name)
        session.add(target)
    target.name = clean_name
    target.description = description.strip()[:MAX_DESC] or None
    target.ranges = parsed_ranges
    target.snmp_version = snmp_version
    target.port = port_num
    target.fdb_enabled = fdb_on
    if community.strip():
        target.community_enc = encrypt_secret(community.strip(),
                                              settings.RANI_INGEST_PEPPER)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="nama grup sudah dipakai")
    await audit(session, request, actor=user.username, action="scan.group.save",
                target=str(target.id), details={"name": clean_name,
                                                "ranges": parsed_ranges})
    await session.commit()
    return RedirectResponse("/agents/groups", status_code=303)


@router.post("/agents/groups/{group_id}/delete")
async def scan_group_delete(group_id: uuid.UUID, request: Request,
                            session: AsyncSession = Depends(get_session),
                            user: AppUser = Depends(require_perm("scan.manage"))):
    group = (await session.execute(
        select(ScanGroup).where(ScanGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="grup tidak ditemukan")
    if running_for(group.id):
        raise HTTPException(status_code=409, detail="scan sedang berjalan untuk grup ini")
    await session.delete(group)
    await audit(session, request, actor=user.username, action="scan.group.delete",
                target=str(group_id), details={"name": group.name})
    await session.commit()
    return RedirectResponse("/agents/groups", status_code=303)


@router.post("/agents/groups/{group_id}/toggle")
async def scan_group_toggle(group_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                            user: AppUser = Depends(require_perm("scan.manage"))):
    group = (await session.execute(
        select(ScanGroup).where(ScanGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="grup tidak ditemukan")
    group.enabled = not group.enabled
    await session.commit()
    return RedirectResponse("/agents/groups", status_code=303)


@router.post("/agents/oids/new")
async def scan_oid_new(request: Request, label: str = Form(""), oid: str = Form(""),
                       description: str = Form(""), vendor: str = Form(""),
                       model: str = Form(""),
                       session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("scan.manage"))):
    label = label.strip()[:96]
    oid = oid.strip()
    error = None
    try:
        if not label:
            raise ScanError("label wajib diisi")
        base = oid[:-2] if oid.endswith(".*") else oid
        if not base or not all(part.isdigit() for part in base.strip(".").split(".")):
            raise ScanError("OID harus angka bertitik, mis. 1.3.6.1.2.1.1.1.0")
        if not base.startswith("1.3.6"):
            raise ScanError("OID harus diawali 1.3.6")
    except ScanError as exc:
        error = str(exc)
    if error:
        return RedirectResponse(f"/agents/groups?oid_error={error[:120]}", status_code=303)
    session.add(ScanOid(label=label, oid=oid, description=description.strip()[:500] or None,
                        vendor=vendor.strip()[:96] or None, model=model.strip()[:96] or None))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return RedirectResponse("/agents/groups?oid_error=OID+itu+sudah+ada", status_code=303)
    await audit(session, request, actor=user.username, action="scan.oid.create",
                target=label, details={"oid": oid})
    await session.commit()
    return RedirectResponse("/agents/groups", status_code=303)


@router.post("/agents/oids/{oid_id}/delete")
async def scan_oid_delete(oid_id: uuid.UUID, request: Request,
                          session: AsyncSession = Depends(get_session),
                          user: AppUser = Depends(require_perm("scan.manage"))):
    row = (await session.execute(
        select(ScanOid).where(ScanOid.id == oid_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="OID tidak ditemukan")
    label = row.label
    await session.delete(row)
    await audit(session, request, actor=user.username, action="scan.oid.delete",
                target=label)
    await session.commit()
    return RedirectResponse("/agents/groups", status_code=303)