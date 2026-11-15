"""UI server-rendered (Jinja2 + AdminLTE 4) + WebSocket + CSV export."""
import csv
import io
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, WebSocket, \
    WebSocketDisconnect
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.api.downloads import artifact_rows
from app.db import get_session
from app.deps import get_current_user_ws, require_perm
from app.models import AppUser, Asset, Software
from app.queries import (dashboard_stats, get_asset_detail, list_agents, list_assets,
                         list_tokens)
from app.actions import load_action_rows, render_actions
from app.widgets import load_enabled
from app.services import create_enrollment_token, revoke_agent
from app.templating import templates
from app.ws import manager

router = APIRouter(include_in_schema=False)


@router.get("/")
async def dashboard(request: Request, session: AsyncSession = Depends(get_session),
                    user: AppUser = Depends(require_perm("dashboard.view"))):
    stats = await dashboard_stats(session)
    widgets = await load_enabled(session)
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"user": user, "stats": stats, "active": "dashboard",
                                       "widgets": widgets,
                                       "can_setup": "setup.manage" in getattr(user, "perm_set", set())})


@router.get("/assets")
async def assets_page(request: Request, q: str | None = None, status: str | None = None,
                      os_family: str | None = None, sort: str = "hostname",
                      order: str = "asc", page: int = Query(1, ge=1),
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("assets.view"))):
    result = await list_assets(session, q, status, os_family, sort, order, page)
    action_rows = await load_action_rows(session)
    base_url = str(request.base_url).rstrip("/")
    for item in result["rows"]:
        item["actions"] = render_actions(action_rows, item["asset"], base_url)
    return templates.TemplateResponse(request, "assets.html",
                                      {"user": user, "result": result, "active": "assets"})


@router.get("/assets/{asset_id}")
async def asset_detail_page(asset_id: str, request: Request,
                            session: AsyncSession = Depends(get_session),
                            user: AppUser = Depends(require_perm("assets.view"))):
    try:
        parsed = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="asset tidak ditemukan")
    detail = await get_asset_detail(session, parsed)
    if detail is None:
        raise HTTPException(status_code=404, detail="asset tidak ditemukan")
    action_rows = await load_action_rows(session)
    base_url = str(request.base_url).rstrip("/")
    detail["actions"] = render_actions(action_rows, detail["asset"], base_url)
    return templates.TemplateResponse(request, "asset_detail.html",
                                      {"user": user, "d": detail, "active": "assets"})


@router.post("/agents/tokens")
async def create_token_form(request: Request, label: str = Form(""),
                            ttl_hours: int = Form(24),
                            session: AsyncSession = Depends(get_session),
                            user: AppUser = Depends(require_perm("agents.manage"))):
    row, raw = await create_enrollment_token(session, label.strip() or None, user.username,
                                             max(1, min(ttl_hours, 720)))
    await audit(session, request, actor=user.username, action="token.create",
                target=str(row.id), details={"label": label})
    await session.commit()
    return RedirectResponse(f"/agents/push?token={raw}", status_code=303)


@router.post("/agents/{agent_id}/revoke")
async def revoke_agent_form(agent_id: uuid.UUID, request: Request,
                            session: AsyncSession = Depends(get_session),
                            user: AppUser = Depends(require_perm("agents.manage"))):
    agent = await revoke_agent(session, agent_id, user.username)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent tidak ditemukan")
    await audit(session, request, actor=user.username, action="agent.revoke",
                target=str(agent.id), details={"name": agent.name})
    await session.commit()
    return RedirectResponse("/agents/push", status_code=303)


@router.get("/export/assets.csv")
async def export_assets(q: str | None = None, status: str | None = None,
                        os_family: str | None = None,
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("assets.export"))):
    """CSV mengikuti filter yang sama dengan halaman /assets (tanpa pagination)."""
    result = await list_assets(session, q, status, os_family, sort="hostname", order="asc",
                               page=1, per_page=5000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["hostname", "ip", "os", "os_version", "vendor", "model", "serial", "mac",
                     "domain", "status", "first_seen", "last_seen", "software_count",
                     "l2_location"])
    for item in result["rows"]:
        asset = item["asset"]
        l2 = "; ".join(f"{x['port']} @ {x['switch_ip'] or x['switch_hostname'] or 'switch'}"
                       for x in item.get("l2") or [])
        writer.writerow([asset.hostname or "", asset.ip_last or "", asset.os_caption or "",
                         asset.os_version or "", asset.vendor or "", asset.model or "",
                         asset.serial or "", asset.primary_mac or "", asset.domain or "",
                         asset.status,
                         asset.first_seen.isoformat() if asset.first_seen else "",
                         asset.last_seen.isoformat() if asset.last_seen else "",
                         item["software_count"], l2])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=rani-assets.csv"})


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket,
                             user: AppUser | None = Depends(get_current_user_ws)):
    if user is None:
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)