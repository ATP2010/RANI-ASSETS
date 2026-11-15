"""Menu Setup → Actions (kelola asset actions ala Lansweeper Configuration > Asset Pages).

Permission: `setup.view` melihat, `setup.manage` mengubah.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions import (ALLOWED_LINK_SCHEMES, ALLOWED_PLACEHOLDERS,
                         render_actions, validate_action)
from app.audit import audit
from app.db import get_session
from app.deps import require_perm
from app.models import AppUser, AssetAction
from app.templating import templates

log = logging.getLogger("rani.setup")
router = APIRouter(include_in_schema=False)

SAMPLE = {
    "hostname": "PC-01", "domain": "corp.local",
    "ip_last": "192.168.88.10", "primary_mac": "bc:24:11:aa:bb:cc",
    "serial": "SN123456", "id": "00000000-0000-0000-0000-0000000000ab",
}


def _now():
    return datetime.now(timezone.utc)


async def _all_actions(session: AsyncSession) -> list[AssetAction]:
    return list((await session.execute(
        select(AssetAction).order_by(AssetAction.advanced.asc(),
                                     AssetAction.sort_order.asc(),
                                     AssetAction.name.asc()))).scalars().all())


async def _load_or_404(session: AsyncSession, action_id: str) -> AssetAction:
    try:
        parsed = uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="action tidak ditemukan") from None
    row = await session.get(AssetAction, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="action tidak ditemukan")
    return row


def _sample_asset():
    class _A:
        pass

    a = _A()
    for key, value in SAMPLE.items():
        setattr(a, key, value)
    return a


@router.get("/setup/actions")
async def setup_actions_page(request: Request, edit: str | None = None,
                             saved: int = 0, error: str | None = None,
                             session: AsyncSession = Depends(get_session),
                             user: AppUser = Depends(require_perm("setup.view"))):
    rows = await _all_actions(session)
    editing = None
    if edit:
        try:
            editing = next((r for r in rows if str(r.id) == edit), None)
        except Exception:  # noqa: BLE001
            editing = None
    preview = render_actions([editing] if editing else rows, _sample_asset(),
                              str(request.base_url).rstrip("/"))
    can_manage = "setup.manage" in user.perm_set
    return templates.TemplateResponse(request, "setup_actions.html", {
        "user": user, "active": "setup", "sub": "actions",
        "base_url": str(request.base_url).rstrip("/"),
        "rows": rows, "editing": editing, "preview": preview,
        "saved": bool(saved), "error": error, "can_manage": can_manage,
        "placeholders": ALLOWED_PLACEHOLDERS,
        "schemes": ALLOWED_LINK_SCHEMES,
        "sample": SAMPLE,
    })


@router.post("/setup/actions")
async def setup_actions_save(request: Request,
                             action_id: str = Form(""),
                             name: str = Form(""), command: str = Form(""),
                             kind: str = Form("link"),
                             enabled: str = Form(""), advanced: str = Form(""),
                             confirm: str = Form(""),
                             sort_order: int = Form(100),
                             session: AsyncSession = Depends(get_session),
                             user: AppUser = Depends(require_perm("setup.manage"))):
    name = (name or "").strip()[:96]
    command = (command or "").strip()
    kind = kind if kind in ("link", "copy", "script") else "link"
    error = validate_action(name, command, kind)
    if error:
        return RedirectResponse(f"/setup/actions?error={error[:150]}", status_code=303)

    target = None
    if action_id:
        target = await _load_or_404(session, action_id)
    creating = target is None
    if target is None:
        max_order = (await session.execute(
            select(func.coalesce(func.max(AssetAction.sort_order), 0)))).scalar_one()
        target = AssetAction(created_at=_now(), updated_at=_now(),
                             sort_order=max(int(sort_order or 0), int(max_order) + 10))
        session.add(target)

    target.name = name
    target.command = command
    target.kind = kind
    target.enabled = enabled.strip().lower() not in ("", "0", "false", "off", "no")
    target.advanced = advanced.strip().lower() not in ("", "0", "false", "off", "no")
    target.confirm = confirm.strip().lower() not in ("", "0", "false", "off", "no")
    target.sort_order = int(sort_order or 100)
    target.updated_at = _now()
    await audit(session, request, actor=user.username,
                action="setup.action.create" if creating else "setup.action.update",
                target=name, details={"kind": kind, "command": command[:200],
                                      "advanced": target.advanced,
                                      "enabled": target.enabled})
    await session.commit()
    return RedirectResponse("/setup/actions?saved=1", status_code=303)


@router.post("/setup/actions/{action_id}/toggle")
async def setup_actions_toggle(action_id: str, request: Request,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("setup.manage"))):
    target = await _load_or_404(session, action_id)
    target.enabled = not target.enabled
    target.updated_at = _now()
    await audit(session, request, actor=user.username, action="setup.action.toggle",
                target=target.name, details={"enabled": target.enabled})
    await session.commit()
    return RedirectResponse("/setup/actions?saved=1", status_code=303)


@router.post("/setup/actions/{action_id}/delete")
async def setup_actions_delete(action_id: str, request: Request,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("setup.manage"))):
    target = await _load_or_404(session, action_id)
    name = target.name
    await session.delete(target)
    await audit(session, request, actor=user.username, action="setup.action.delete",
                target=name)
    await session.commit()
    return RedirectResponse("/setup/actions?saved=1", status_code=303)


@router.post("/setup/actions/{action_id}/duplicate")
async def setup_actions_duplicate(action_id: str, request: Request,
                                  session: AsyncSession = Depends(get_session),
                                  user: AppUser = Depends(require_perm("setup.manage"))):
    source = await _load_or_404(session, action_id)
    max_order = (await session.execute(
        select(func.coalesce(func.max(AssetAction.sort_order), 0)))).scalar_one()
    clone = AssetAction(
        name=f"Salinan {source.name}"[:96], command=source.command, kind=source.kind,
        enabled=source.enabled, advanced=source.advanced, confirm=source.confirm,
        sort_order=int(max_order) + 10,
        created_at=_now(), updated_at=_now())
    session.add(clone)
    await audit(session, request, actor=user.username, action="setup.action.create",
                target=clone.name, details={"duplicated_from": source.name})
    await session.commit()
    return RedirectResponse("/setup/actions?saved=1", status_code=303)


@router.post("/setup/actions/{action_id}/move")
async def setup_actions_move(action_id: str, request: Request, dir: str = Form("up"),
                             session: AsyncSession = Depends(get_session),
                             user: AppUser = Depends(require_perm("setup.manage"))):
    rows = await _all_actions(session)
    idx = next((i for i, r in enumerate(rows) if str(r.id) == action_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="action tidak ditemukan")
    neighbor_idx = idx - 1 if dir == "up" else idx + 1
    if neighbor_idx < 0 or neighbor_idx >= len(rows):
        return RedirectResponse("/setup/actions", status_code=303)
    a, b = rows[idx], rows[neighbor_idx]
    a.sort_order, b.sort_order = b.sort_order, a.sort_order
    if a.sort_order == b.sort_order:  # tabrakan order — normalisasi selisih 10
        a.sort_order = b.sort_order + (10 if dir == "up" else -10)
    a.updated_at = _now()
    b.updated_at = _now()
    await session.commit()
    return RedirectResponse("/setup/actions", status_code=303)


# ---------------------------------------------------------------- Setup → Dashboard
from app.models import DashboardWidget
from app.queries import list_reports
from app.widgets import (BUILTIN_KINDS, WIDGET_KINDS, WIDGET_WIDTHS,
                         load_enabled, preview_report)


async def _all_widgets(session: AsyncSession) -> list[DashboardWidget]:
    return list((await session.execute(
        select(DashboardWidget).order_by(DashboardWidget.sort_order.asc(),
                                         DashboardWidget.title.asc())
    )).scalars().all())


async def _load_widget_or_404(session: AsyncSession, widget_id: str) -> DashboardWidget:
    try:
        parsed = uuid.UUID(widget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="widget tidak ditemukan") from None
    row = await session.get(DashboardWidget, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="widget tidak ditemukan")
    return row


@router.get("/setup/dashboard")
async def setup_dashboard_page(request: Request, edit: str | None = None,
                               report_id: str | None = None,
                               saved: int = 0, error: str | None = None,
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("setup.view"))):
    rows = await _all_widgets(session)
    report_rows = await list_reports(session, user)
    report_names = {str(r["report"].id): r["report"].name for r in report_rows}
    can_manage = "setup.manage" in user.perm_set

    editing = None
    if edit:
        try:
            editing = next((r for r in rows if str(r.id) == edit), None)
        except Exception:  # noqa: BLE001
            editing = None

    selected_report = report_id or (str(editing.report_id) if editing and editing.report_id else "")
    preview = await preview_report(session, uuid.UUID(selected_report)) \
        if selected_report else {"columns": [], "rows": [], "error": None, "name": None}
    return templates.TemplateResponse(request, "setup_dashboard.html", {
        "user": user, "active": "setup", "sub": "dashboard",
        "rows": rows, "editing": editing, "preview": preview,
        "selected_report": selected_report,
        "kinds": WIDGET_KINDS, "widths": WIDGET_WIDTHS,
        "builtin_kinds": [k for k, _ in BUILTIN_KINDS],
        "report_options": [{"id": str(r["report"].id),
                            "name": r["report"].name,
                            "owner": r["owner"]} for r in report_rows],
        "report_names": report_names,
        "saved": bool(saved), "error": error, "can_manage": can_manage,
        "base_url": str(request.base_url).rstrip("/"),
    })


@router.post("/setup/dashboard")
async def setup_dashboard_save(request: Request,
                               widget_id: str = Form(""),
                               title: str = Form(""),
                               kind: str = Form("donut"),
                               report_id: str = Form(""),
                               x_col: str = Form(""),
                               y_col: str = Form(""),
                               width: str = Form("col-lg-4"),
                               sort_order: int = Form(100),
                               enabled: str = Form(""),
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("setup.manage"))):
    title = (title or "").strip()[:96]
    kind = kind if kind in dict(WIDGET_KINDS) else "donut"
    width = width if width in dict(WIDGET_WIDTHS) else "col-lg-4"
    if not title:
        return RedirectResponse("/setup/dashboard?error=judul+widget+wajib+diisi",
                                status_code=303)

    # widget bawaan: report diabaikan
    builtin = kind in dict(BUILTIN_KINDS)
    report_uuid = None
    report = None
    if report_id and not builtin:
        try:
            report_uuid = uuid.UUID(report_id)
        except ValueError:
            return RedirectResponse("/setup/dashboard?error=report+tidak+valid",
                                    status_code=303)
        from app.models import Report as _Report
        report = await session.get(_Report, report_uuid)
        if report is None:
            return RedirectResponse("/setup/dashboard?error=report+tidak+ditemukan",
                                    status_code=303)

    target = None
    if widget_id:
        target = await _load_widget_or_404(session, widget_id)
    creating = target is None
    if target is None:
        max_order = (await session.execute(
            select(func.coalesce(func.max(DashboardWidget.sort_order), 0)))).scalar_one()
        target = DashboardWidget(created_at=_now(), updated_at=_now(),
                                 sort_order=int(sort_order or 0) or int(max_order) + 10)
        session.add(target)

    target.title = title
    target.kind = kind
    target.report_id = report_uuid
    target.x_col = x_col.strip()[:96] or None
    target.y_col = y_col.strip()[:96] or None
    target.width = width
    target.sort_order = int(sort_order or 100)
    target.enabled = enabled.strip().lower() not in ("", "0", "false", "off", "no")
    target.updated_at = _now()
    await audit(session, request, actor=user.username,
                action="setup.widget.create" if creating else "setup.widget.update",
                target=title,
                details={"kind": kind, "report": report.name if report else None,
                         "width": width, "enabled": target.enabled})
    await session.commit()
    return RedirectResponse("/setup/dashboard?saved=1", status_code=303)


@router.post("/setup/dashboard/{widget_id}/toggle")
async def setup_dashboard_toggle(widget_id: str, request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 user: AppUser = Depends(require_perm("setup.manage"))):
    target = await _load_widget_or_404(session, widget_id)
    target.enabled = not target.enabled
    target.updated_at = _now()
    await audit(session, request, actor=user.username, action="setup.widget.toggle",
                target=target.title, details={"enabled": target.enabled})
    await session.commit()
    return RedirectResponse("/setup/dashboard?saved=1", status_code=303)


@router.post("/setup/dashboard/{widget_id}/delete")
async def setup_dashboard_delete(widget_id: str, request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 user: AppUser = Depends(require_perm("setup.manage"))):
    target = await _load_widget_or_404(session, widget_id)
    title = target.title
    await session.delete(target)
    await audit(session, request, actor=user.username, action="setup.widget.delete",
                target=title)
    await session.commit()
    return RedirectResponse("/setup/dashboard?saved=1", status_code=303)


@router.post("/setup/dashboard/{widget_id}/duplicate")
async def setup_dashboard_duplicate(widget_id: str, request: Request,
                                    session: AsyncSession = Depends(get_session),
                                    user: AppUser = Depends(require_perm("setup.manage"))):
    source = await _load_widget_or_404(session, widget_id)
    max_order = (await session.execute(
        select(func.coalesce(func.max(DashboardWidget.sort_order), 0)))).scalar_one()
    clone = DashboardWidget(
        title=f"Salinan {source.title}"[:96], kind=source.kind,
        report_id=source.report_id, x_col=source.x_col, y_col=source.y_col,
        width=source.width, sort_order=int(max_order) + 10,
        enabled=source.enabled, created_at=_now(), updated_at=_now())
    session.add(clone)
    await audit(session, request, actor=user.username, action="setup.widget.create",
                target=clone.title, details={"duplicated_from": source.title})
    await session.commit()
    return RedirectResponse("/setup/dashboard?saved=1", status_code=303)


@router.post("/setup/dashboard/{widget_id}/move")
async def setup_dashboard_move(widget_id: str, request: Request, dir: str = Form("up"),
                               session: AsyncSession = Depends(get_session),
                               user: AppUser = Depends(require_perm("setup.manage"))):
    rows = await _all_widgets(session)
    idx = next((i for i, r in enumerate(rows) if str(r.id) == widget_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="widget tidak ditemukan")
    neighbor = idx - 1 if dir == "up" else idx + 1
    if neighbor < 0 or neighbor >= len(rows):
        return RedirectResponse("/setup/dashboard", status_code=303)
    a, b = rows[idx], rows[neighbor]
    a.sort_order, b.sort_order = b.sort_order, a.sort_order
    if a.sort_order == b.sort_order:
        a.sort_order = b.sort_order + (10 if dir == "up" else -10)
    a.updated_at = _now()
    b.updated_at = _now()
    await session.commit()
    return RedirectResponse("/setup/dashboard", status_code=303)
