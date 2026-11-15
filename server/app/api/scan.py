"""API scan SNMP: mulai scan, status/Progres, hasil, cancel."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import require_perm
from app.models import AppUser, ScanGroup, ScanResult, ScanRun
from app.scanner import ScanError, execute_scan, register_run, running_for

log = logging.getLogger("rani.scan.api")
router = APIRouter(tags=["scan"])

_TASKS: set[asyncio.Task] = set()


@router.post("/api/v1/scan/groups/{group_id}/run")
async def start_scan(group_id: uuid.UUID, request: Request,
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("scan.run"))) -> dict:
    group = (await session.execute(
        select(ScanGroup).where(ScanGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="grup scan tidak ditemukan")
    if not group.enabled:
        raise HTTPException(status_code=400, detail="grup scan nonaktif")
    active = running_for(group_id)
    if active:
        return {"run_id": active, "already_running": True}

    run = ScanRun(group_id=group.id, status="running", created_by=user.username,
                  stats={"group": group.name})
    session.add(run)
    await session.flush()
    await audit(session, request, actor=user.username, action="scan.start",
                target=str(run.id), details={"group": group.name, "ranges": group.ranges})
    await session.commit()

    register_run(group.id, run.id)
    task = asyncio.create_task(execute_scan(run.id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"run_id": str(run.id), "already_running": False}


@router.get("/api/v1/scan/runs/{run_id}")
async def scan_status(run_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("scan.view"))) -> dict:
    run = (await session.execute(
        select(ScanRun).where(ScanRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="scan tidak ditemukan")
    rows = (await session.execute(
        select(ScanResult).where(ScanResult.run_id == run_id)
        .order_by(ScanResult.ip).limit(500))).scalars().all()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "group_id": str(run.group_id) if run.group_id else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "hosts_total": run.hosts_total,
        "hosts_done": run.hosts_done,
        "hosts_found": run.hosts_found,
        "error": run.error,
        "stats": run.stats or {},
        "results": [{
            "ip": r.ip, "status": r.status, "sys_name": r.sys_name,
            "sys_object_id": r.sys_object_id, "sys_descr": (r.sys_descr or "")[:160],
            "vendor": r.vendor, "model": r.model, "serial": r.serial,
            "uptime_s": r.uptime_s, "if_count": r.if_count, "fdb_count": r.fdb_count,
            "oid_values": r.oid_values or {}, "error": r.error,
            "asset_id": str(r.asset_id) if r.asset_id else None,
        } for r in rows],
    }


@router.post("/api/v1/scan/runs/{run_id}/cancel")
async def cancel_scan(run_id: uuid.UUID, request: Request,
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("scan.run"))) -> dict:
    run = (await session.execute(
        select(ScanRun).where(ScanRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="scan tidak ditemukan")
    if run.status != "running":
        raise HTTPException(status_code=409, detail=f"scan sudah {run.status}")
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    await audit(session, request, actor=user.username, action="scan.cancel",
                target=str(run.id), outcome="success")
    await session.commit()
    return {"run_id": str(run.id), "status": "cancelled"}