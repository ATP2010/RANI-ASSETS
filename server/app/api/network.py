"""API port map Layer-2 (bridge FDB): ringkasan per switch, baris MAC↔port, lookup."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_perm
from app.models import AppUser
from app.queries import list_port_map, port_map_summary

router = APIRouter(tags=["network"])


def _serialize(row: dict) -> dict:
    m = row["mapping"]
    return {
        "mac": m.mac,
        "vlan": m.vlan,
        "switch_asset_id": str(m.switch_asset_id),
        "switch_hostname": row["switch_hostname"],
        "switch_ip": row["switch_ip"],
        "port": m.if_name,
        "if_index": m.if_index,
        "bridge_port": m.bridge_port,
        "status": m.status,
        "present": m.present,
        "endpoint_asset_id": str(m.endpoint_asset_id) if m.endpoint_asset_id else None,
        "endpoint_hostname": row["endpoint_hostname"],
        "endpoint_type": row["endpoint_type"],
        "first_seen": m.first_seen.isoformat() if m.first_seen else None,
        "last_seen": m.last_seen.isoformat() if m.last_seen else None,
    }


@router.get("/api/v1/network/port-map")
async def port_map(switch: str | None = None, q: str | None = None,
                   present: bool = True,
                   limit: int = Query(2000, ge=1, le=5000),
                   session: AsyncSession = Depends(get_session),
                   user: AppUser = Depends(require_perm("portmap.view"))) -> dict:
    """Ringkasan semua switch + baris MAC↔port. `switch` = UUID asset network."""
    switch_id = None
    if switch:
        try:
            switch_id = uuid.UUID(switch)
        except ValueError:
            raise HTTPException(status_code=400, detail="switch bukan UUID asset")
    rows = await list_port_map(session, switch_id=switch_id, q=q,
                               present_only=present, limit=limit)
    return {
        "summary": [{
            "switch_asset_id": str(s["switch_asset_id"]),
            "hostname": s["hostname"], "ip": s["ip_last"], "vendor": s["vendor"],
            "model": s["model"], "macs": s["macs"], "ports": s["ports"],
            "known": s["known"],
            "last_seen": s["last_seen"].isoformat() if s["last_seen"] else None,
        } for s in await port_map_summary(session)],
        "rows": [_serialize(r) for r in rows],
        "count": len(rows),
    }


@router.get("/api/v1/network/lookup")
async def lookup(q: str = Query(..., min_length=2, max_length=128),
                 session: AsyncSession = Depends(get_session),
                 user: AppUser = Depends(require_perm("portmap.view"))) -> dict:
    """Cari MAC / hostname / nama port → di switch dan port mana saja terlihat."""
    rows = await list_port_map(session, q=q, limit=200)
    return {"query": q, "count": len(rows), "results": [_serialize(r) for r in rows]}
