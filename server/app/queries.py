"""Query baca (dipakai UI server-rendered dan JSON API — satu sumber kebenaran)."""
import re
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (Agent, Asset, AssetSource, AppUser, EndpointPortMapping,
                        EnrollmentToken, HwComponent, NetworkInterface, Report,
                        SecurityState, Software, SoftwareEvent, SoftwareReport, UserSeen)

DISPLAY_TZ = ZoneInfo("Asia/Jakarta")  # label jam/tanggal di UI selalu WIB

SORT_COLUMNS = {
    "hostname": Asset.hostname,
    "last_seen": Asset.last_seen,
    "first_seen": Asset.first_seen,
    "status": Asset.status,
    "os": Asset.os_caption,
    "ip": Asset.ip_last,
}


def _software_count_subquery():
    return (select(func.count(Software.id))
            .where(Software.asset_id == Asset.id, Software.present.is_(True))
            .scalar_subquery())


def port_name_sort_key(name: str | None):
    """Natural sort nama port: Gi0/2 < Gi0/10 (bukan leksikografis)."""
    text = str(name or "").lower()
    match = re.match(r"^(.*?)(\d+)\s*$", text)
    if not match:
        return (text, 0)
    return (match.group(1), int(match.group(2)))


async def _l2_locations(session: AsyncSession,
                        assets: list) -> tuple[dict, dict]:
    """Lokasi L2 (endpoint) + utilisasi port (switch) untuk sekumpulan asset.

    Return (by_endpoint, by_switch):
      by_endpoint[asset_id] -> [{"port","vlan","mac","status","switch_id","switch_hostname","switch_ip"}]
      by_switch[asset_id]   -> {"macs","ports","known"}

    Endpoint dicocokkan dua jalur: (1) `endpoint_asset_id` hasil scan/reconcile,
    (2) MAC asset (primary_mac + MAC di network_interfaces) yang belum tertaut —
    supaya PC yang baru di-enroll langsung terlihat posisinya.
    """
    ids = [a.id for a in assets]
    if not ids:
        return {}, {}
    switch = aliased(Asset)

    def _add(out, seen, asset_id, row):
        key = (asset_id, row["switch_id"], row["port"], row["mac"])
        if key in seen:
            return
        seen.add(key)
        out.setdefault(asset_id, []).append(row)

    def _row(if_name, vlan, mac, status, sid, shostname, s_ip):
        return {"port": if_name or "—", "vlan": vlan, "mac": mac, "status": status,
                "switch_id": sid, "switch_hostname": shostname, "switch_ip": s_ip}

    rows = (await session.execute(
        select(EndpointPortMapping.endpoint_asset_id,
               EndpointPortMapping.if_name, EndpointPortMapping.vlan,
               EndpointPortMapping.mac, EndpointPortMapping.status,
               switch.id.label("switch_id"),
               switch.hostname.label("switch_hostname"),
               switch.ip_last.label("switch_ip"))
        .join(switch, switch.id == EndpointPortMapping.switch_asset_id)
        .where(EndpointPortMapping.endpoint_asset_id.in_(ids),
               EndpointPortMapping.present.is_(True))
        .order_by(switch.hostname.asc(), EndpointPortMapping.if_name.asc())
    )).all()
    by_endpoint: dict = {}
    seen: set = set()
    for endpoint_id, if_name, vlan, mac, status, sid, shostname, s_ip in rows:
        _add(by_endpoint, seen, endpoint_id,
             _row(if_name, vlan, mac, status, sid, shostname, s_ip))

    # Fallback: MAC asset yang belum tertaut ke endpoint_asset_id
    macs_by_asset: dict = {}
    for a in assets:
        if a.primary_mac:
            macs_by_asset.setdefault(a.id, set()).add(str(a.primary_mac).lower())
    iface_rows = (await session.execute(
        select(NetworkInterface.asset_id, NetworkInterface.mac)
        .where(NetworkInterface.asset_id.in_(ids), NetworkInterface.mac.isnot(None))
    )).all()
    for asset_id, mac in iface_rows:
        if mac:
            macs_by_asset.setdefault(asset_id, set()).add(str(mac).lower())
    mac_owner: dict = {}
    for asset_id, macs in macs_by_asset.items():
        for mac in macs:
            mac_owner.setdefault(mac, []).append(asset_id)
    if mac_owner:
        mac_rows = (await session.execute(
            select(EndpointPortMapping.mac,
                   EndpointPortMapping.if_name, EndpointPortMapping.vlan,
                   EndpointPortMapping.status,
                   switch.id.label("switch_id"),
                   switch.hostname.label("switch_hostname"),
                   switch.ip_last.label("switch_ip"))
            .join(switch, switch.id == EndpointPortMapping.switch_asset_id)
            .where(EndpointPortMapping.present.is_(True),
                   EndpointPortMapping.endpoint_asset_id.is_(None),
                   EndpointPortMapping.mac.in_(sorted(mac_owner)))
            .order_by(switch.hostname.asc(), EndpointPortMapping.if_name.asc())
        )).all()
        for mac, if_name, vlan, status, sid, shostname, s_ip in mac_rows:
            for asset_id in mac_owner.get(str(mac).lower(), []):
                _add(by_endpoint, seen, asset_id,
                     _row(if_name, vlan, mac, status, sid, shostname, s_ip))

    counts = (await session.execute(
        select(EndpointPortMapping.switch_asset_id,
               func.count(func.distinct(EndpointPortMapping.mac)).label("macs"),
               func.count(func.distinct(EndpointPortMapping.if_name)).label("ports"),
               func.count(func.distinct(EndpointPortMapping.endpoint_asset_id))
               .label("known"))
        .where(EndpointPortMapping.switch_asset_id.in_(ids),
               EndpointPortMapping.present.is_(True))
        .group_by(EndpointPortMapping.switch_asset_id)
    )).all()
    by_switch: dict = {}
    for switch_id, macs, ports, known in counts:
        by_switch[switch_id] = {"macs": macs, "ports": ports, "known": known}
    return by_endpoint, by_switch


async def list_assets(session: AsyncSession, q: str | None = None, status: str | None = None,
                      os_family: str | None = None, sort: str = "hostname", order: str = "asc",
                      page: int = 1, per_page: int = 25) -> dict:
    stmt = select(Asset, _software_count_subquery().label("software_count"))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Asset.hostname.ilike(like), Asset.ip_last.ilike(like),
                              Asset.serial.ilike(like), Asset.primary_mac.ilike(like),
                              Asset.model.ilike(like), Asset.os_caption.ilike(like)))
    if status in ("online", "offline"):
        stmt = stmt.where(Asset.status == status)
    if os_family:
        stmt = stmt.where(Asset.os_family == os_family)

    total = (await session.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )).scalar_one()

    column = SORT_COLUMNS.get(sort, Asset.hostname)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
    page = max(page, 1)
    per_page = min(max(per_page, 5), 200)
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(stmt)).all()
    pages = max((total + per_page - 1) // per_page, 1)
    by_endpoint, by_switch = await _l2_locations(session, [a for a, _ in rows])
    return {
        "rows": [{"asset": asset, "software_count": count,
                  "l2": by_endpoint.get(asset.id, []),
                  "occ": by_switch.get(asset.id)} for asset, count in rows],
        "total": total, "page": page, "per_page": per_page, "pages": pages,
        "q": q or "", "status": status or "", "os_family": os_family or "",
        "sort": sort, "order": order,
    }


async def get_asset_detail(session: AsyncSession, asset_id: uuid.UUID) -> dict | None:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        return None
    software = (await session.execute(
        select(Software).where(Software.asset_id == asset_id)
        .order_by(Software.present.desc(), Software.name_norm.asc())
    )).scalars().all()
    hw = (await session.execute(
        select(HwComponent).where(HwComponent.asset_id == asset_id)
        .order_by(HwComponent.class_.asc(), HwComponent.key.asc())
    )).scalars().all()
    users = (await session.execute(
        select(UserSeen).where(UserSeen.asset_id == asset_id)
        .order_by(UserSeen.role.asc(), UserSeen.username.asc())
    )).scalars().all()
    security = (await session.execute(
        select(SecurityState).where(SecurityState.asset_id == asset_id)
        .order_by(SecurityState.checked_at.desc()).limit(1)
    )).scalar_one_or_none()
    interfaces = (await session.execute(
        select(NetworkInterface).where(NetworkInterface.asset_id == asset_id)
        .order_by(NetworkInterface.name.asc())
    )).scalars().all()
    reports = (await session.execute(
        select(SoftwareReport).where(SoftwareReport.asset_id == asset_id)
        .order_by(SoftwareReport.received_at.desc()).limit(20)
    )).scalars().all()
    events = (await session.execute(
        select(SoftwareEvent).where(SoftwareEvent.asset_id == asset_id)
        .order_by(SoftwareEvent.at.desc()).limit(100)
    )).scalars().all()
    sources = (await session.execute(
        select(AssetSource).where(AssetSource.asset_id == asset_id)
        .order_by(AssetSource.ts.desc()).limit(20)
    )).scalars().all()

    port_map: list[dict] = []
    port_map_stale = 0
    if asset.asset_type == "network":
        port_map = await list_port_map(session, switch_id=asset_id, limit=2000)
        port_map.sort(key=lambda r: port_name_sort_key(r["mapping"].if_name))
        port_map_stale = (await session.execute(
            select(func.count(EndpointPortMapping.id))
            .where(EndpointPortMapping.switch_asset_id == asset_id,
                   EndpointPortMapping.present.is_(False)))).scalar_one()

    by_class: dict[str, list[HwComponent]] = {}
    for component in hw:
        by_class.setdefault(component.class_, []).append(component)

    by_endpoint, _by_switch = await _l2_locations(session, [asset])
    return {
        "asset": asset, "software": software,
        "software_present": [s for s in software if s.present],
        "software_absent": [s for s in software if not s.present],
        "hardware": by_class, "users": users, "security": security,
        "interfaces": interfaces, "reports": reports, "events": events, "sources": sources,
        "port_map": port_map, "port_map_stale": port_map_stale,
        "port_map_ports": len({r["mapping"].if_name for r in port_map if r["mapping"].if_name}),
        "l2": by_endpoint.get(asset.id, []),
    }


async def dashboard_stats(session: AsyncSession) -> dict:
    total = (await session.execute(select(func.count(Asset.id)))).scalar_one()
    online = (await session.execute(
        select(func.count(Asset.id)).where(Asset.status == "online"))).scalar_one()
    software_titles = (await session.execute(
        select(func.count(func.distinct(Software.name_norm))).where(Software.present.is_(True))
    )).scalar_one()
    software_rows = (await session.execute(
        select(func.count(Software.id)).where(Software.present.is_(True)))).scalar_one()

    os_rows = (await session.execute(
        select(func.coalesce(Asset.os_caption, "unknown").label("os"), func.count(Asset.id))
        .group_by("os").order_by(func.count(Asset.id).desc()).limit(8)
    )).all()
    top_rows = (await session.execute(
        select(Software.name_raw, func.count(func.distinct(Software.asset_id)).label("c"))
        .where(Software.present.is_(True))
        .group_by(Software.name_raw).order_by(func.count(func.distinct(Software.asset_id)).desc())
        .limit(8)
    )).all()

    # 24 bucket per jam termasuk jam tanpa push, supaya grafik tren tidak bolong.
    # generate_series memakai timezone sesi DB yang sama dengan date_trunc → bucket
    # selalu sejajar dengan label jam yang dikirim ke UI.
    trend_rows = (await session.execute(text(
        """
        SELECT gs.hour AS hour, count(r.id) AS count
          FROM generate_series(date_trunc('hour', now()) - interval '23 hours',
                               date_trunc('hour', now()),
                               interval '1 hour') AS gs(hour)
          LEFT JOIN rani_inventory.software_reports r
                 ON date_trunc('hour', r.received_at) = gs.hour
         GROUP BY gs.hour
         ORDER BY gs.hour
        """
    ))).all()

    recent_events = (await session.execute(
        select(SoftwareEvent, Software.name_raw, Asset.hostname)
        .join(Asset, Asset.id == SoftwareEvent.asset_id)
        .outerjoin(Software, Software.id == SoftwareEvent.software_id)
        .order_by(SoftwareEvent.at.desc()).limit(12)
    )).all()

    return {
        "assets_total": total,
        "assets_online": online,
        "assets_offline": total - online,
        "software_titles": software_titles,
        "software_installs": software_rows,
        "os_mix": [{"label": label, "count": count} for label, count in os_rows],
        "top_software": [{"label": str(label), "count": count} for label, count in top_rows],
        "reports_trend": [{"hour": hour.astimezone(DISPLAY_TZ).isoformat(),
                           "count": count} for hour, count in trend_rows],
        "recent_events": [{"event": ev.event,
                           "at": ev.at.astimezone(DISPLAY_TZ).isoformat(),
                           "name": name, "hostname": hostname,
                           "software_id": str(ev.software_id) if ev.software_id else None}
                          for ev, name, hostname in recent_events],
    }


async def port_map_summary(session: AsyncSession) -> list[dict]:
    """Ringkasan port map per switch: jumlah MAC aktif, port terpakai, endpoint dikenal."""
    rows = (await session.execute(text(
        """
        SELECT a.id AS switch_asset_id, a.hostname, a.ip_last, a.vendor, a.model,
               count(m.id) FILTER (WHERE m.present) AS macs,
               count(DISTINCT m.if_name) FILTER (WHERE m.present AND m.if_name IS NOT NULL)
                   AS ports,
               count(DISTINCT m.endpoint_asset_id) FILTER (WHERE m.present) AS known,
               max(m.last_seen) AS last_seen
          FROM rani_inventory.assets a
          JOIN rani_inventory.endpoint_port_mappings m ON m.switch_asset_id = a.id
         GROUP BY a.id, a.hostname, a.ip_last, a.vendor, a.model
         ORDER BY macs DESC, a.hostname
        """
    ))).all()
    return [{"switch_asset_id": r.switch_asset_id, "hostname": r.hostname,
             "ip_last": r.ip_last, "vendor": r.vendor, "model": r.model,
             "macs": r.macs, "ports": r.ports, "known": r.known,
             "last_seen": r.last_seen} for r in rows]


async def list_port_map(session: AsyncSession, switch_id: uuid.UUID | None = None,
                        q: str | None = None, present_only: bool = True,
                        limit: int = 2000) -> list[dict]:
    """Baris MAC↔port (opsional satu switch). `q` mencari MAC, nama port, hostname."""
    switch = aliased(Asset)
    endpoint = aliased(Asset)
    stmt = (select(EndpointPortMapping,
                   switch.hostname.label("switch_hostname"),
                   switch.ip_last.label("switch_ip"),
                   endpoint.hostname.label("endpoint_hostname"),
                   endpoint.asset_type.label("endpoint_type"))
            .join(switch, switch.id == EndpointPortMapping.switch_asset_id)
            .outerjoin(endpoint, endpoint.id == EndpointPortMapping.endpoint_asset_id))
    if switch_id is not None:
        stmt = stmt.where(EndpointPortMapping.switch_asset_id == switch_id)
    if present_only:
        stmt = stmt.where(EndpointPortMapping.present.is_(True))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(EndpointPortMapping.mac.ilike(like),
                              EndpointPortMapping.if_name.ilike(like),
                              switch.hostname.ilike(like),
                              switch.ip_last.ilike(like),
                              endpoint.hostname.ilike(like)))
    stmt = (stmt.order_by(switch.hostname.asc(), EndpointPortMapping.if_name.asc(),
                          EndpointPortMapping.mac.asc())
            .limit(min(max(limit, 1), 5000)))
    rows = (await session.execute(stmt)).all()
    return [{"mapping": mapping, "switch_hostname": switch_hostname,
             "switch_ip": switch_ip, "endpoint_hostname": endpoint_hostname,
             "endpoint_type": endpoint_type}
            for mapping, switch_hostname, switch_ip, endpoint_hostname, endpoint_type in rows]


async def list_agents(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(
        select(Agent).order_by(Agent.enrolled_at.desc())
    )).scalars().all()
    out = []
    for agent in rows:
        asset = None
        if agent.machine_id:
            asset = (await session.execute(
                select(Asset).where(Asset.agent_id == agent.id).limit(1)
            )).scalar_one_or_none()
        out.append({"agent": agent, "hostname": asset.hostname if asset else None,
                    "asset_id": asset.id if asset else None,
                    "last_seen": asset.last_seen if asset else agent.last_seen})
    return out


async def list_reports(session: AsyncSession, user: AppUser) -> list[dict]:
    """Report yang boleh dilihat user: shared, miliknya, atau semua bila reports.manage."""
    stmt = (select(Report, AppUser.username)
            .outerjoin(AppUser, AppUser.id == Report.owner_id))
    if "reports.manage" not in getattr(user, "perm_set", set()):
        stmt = stmt.where(or_(Report.is_shared.is_(True), Report.owner_id == user.id))
    rows = (await session.execute(stmt.order_by(Report.updated_at.desc()))).all()
    return [{"report": report, "owner": owner} for report, owner in rows]


async def get_report(session: AsyncSession, report_id: uuid.UUID,
                     user: AppUser) -> dict | None:
    row = (await session.execute(
        select(Report, AppUser.username)
        .outerjoin(AppUser, AppUser.id == Report.owner_id)
        .where(Report.id == report_id)
    )).first()
    if row is None:
        return None
    report, owner = row
    if not (report.is_shared or report.owner_id == user.id
                or "reports.manage" in getattr(user, "perm_set", set())):
        return None
    return {"report": report, "owner": owner}


async def list_tokens(session: AsyncSession) -> list[EnrollmentToken]:
    return (await session.execute(
        select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc()).limit(20)
    )).scalars().all()