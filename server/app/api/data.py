"""JSON API: assets, stats, agents, enrollment token (untuk integrasi & MCP nanti)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import require_perm
from app.models import AppUser
from app.queries import dashboard_stats, get_asset_detail, list_agents, list_assets
from app.services import create_enrollment_token, revoke_agent

router = APIRouter(prefix="/api/v1", tags=["data"])


@router.get("/assets")
async def api_assets(q: str | None = None, status: str | None = None,
                     os_family: str | None = None, sort: str = "hostname",
                     order: str = "asc", page: int = Query(1, ge=1),
                     per_page: int = Query(25, ge=1, le=200),
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("assets.view"))) -> dict:
    result = await list_assets(session, q, status, os_family, sort, order, page, per_page)
    return {
        "total": result["total"], "page": result["page"], "pages": result["pages"],
        "items": [{
            "id": str(asset.id), "hostname": asset.hostname, "ip": asset.ip_last,
            "os": asset.os_caption, "status": asset.status,
            "last_seen": asset.last_seen.isoformat() if asset.last_seen else None,
            "serial": asset.serial, "mac": asset.primary_mac,
            "software_count": count,
        } for asset, count in ((i["asset"], i["software_count"]) for i in result["rows"])],
    }


@router.get("/assets/{asset_id}")
async def api_asset_detail(asset_id: uuid.UUID,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("assets.view"))) -> dict:
    detail = await get_asset_detail(session, asset_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="asset tidak ditemukan")
    asset = detail["asset"]
    return {
        "asset": {
            "id": str(asset.id), "hostname": asset.hostname, "domain": asset.domain,
            "os": asset.os_caption, "os_version": asset.os_version, "os_build": asset.os_build,
            "serial": asset.serial, "vendor": asset.vendor, "model": asset.model,
            "mac": asset.primary_mac, "ip": asset.ip_last, "status": asset.status,
            "first_seen": asset.first_seen.isoformat() if asset.first_seen else None,
            "last_seen": asset.last_seen.isoformat() if asset.last_seen else None,
            "attrs": asset.attrs,
        },
        "software": [{"name": s.name_raw, "version": s.version, "vendor": s.vendor,
                      "present": s.present} for s in detail["software"]],
        "hardware": {cls: [{"key": c.key, "attrs": c.attrs, "present": c.present}
                           for c in items] for cls, items in detail["hardware"].items()},
        "users": [{"username": u.username, "role": u.role} for u in detail["users"]],
        "interfaces": [{"name": i.name, "mac": i.mac, "ipv4": i.ipv4, "gateway": i.gateway}
                       for i in detail["interfaces"]],
    }


@router.get("/stats")
async def api_stats(session: AsyncSession = Depends(get_session),
                    user: AppUser = Depends(require_perm("dashboard.view"))) -> dict:
    return await dashboard_stats(session)


@router.get("/agents")
async def api_agents(session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("agents.view"))) -> list[dict]:
    return [{"id": str(a["agent"].id), "name": a["agent"].name,
             "machine_id": a["agent"].machine_id, "revoked_at": a["agent"].revoked_at,
             "last_seen": a["last_seen"].isoformat() if a["last_seen"] else None,
             "version": a["agent"].agent_version, "hostname": a["hostname"]}
            for a in await list_agents(session)]


class TokenRequest(BaseModel):
    label: str | None = None
    ttl_hours: int = 24


@router.post("/enrollment-tokens")
async def api_create_token(body: TokenRequest, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("agents.manage"))) -> dict:
    row, raw = await create_enrollment_token(session, body.label, user.username,
                                             max(1, min(body.ttl_hours, 720)))
    await audit(session, request, actor=user.username, action="token.create",
                target=str(row.id), details={"label": body.label})
    await session.commit()
    return {"token": raw, "id": str(row.id), "expires_at":
            row.expires_at.isoformat() if row.expires_at else None}


@router.post("/agents/{agent_id}/revoke")
async def api_revoke_agent(agent_id: uuid.UUID, request: Request,
                           session: AsyncSession = Depends(get_session),
                           user: AppUser = Depends(require_perm("agents.manage"))) -> dict:
    agent = await revoke_agent(session, agent_id, user.username)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent tidak ditemukan")
    agent.revoked_at = agent.revoked_at or datetime.now(timezone.utc)
    await audit(session, request, actor=user.username, action="agent.revoke",
                target=str(agent.id), details={"name": agent.name})
    await session.commit()
    return {"id": str(agent.id), "revoked": True}