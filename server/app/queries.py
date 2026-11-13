"""Query baca (dipakai UI server-rendered dan JSON API — satu sumber kebenaran)."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Agent, Asset, AssetSource, EnrollmentToken, HwComponent,
                        NetworkInterface, SecurityState, Software, SoftwareEvent,
                        SoftwareReport, UserSeen)

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
    return {
        "rows": [{"asset": asset, "software_count": count} for asset, count in rows],
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

    by_class: dict[str, list[HwComponent]] = {}
    for component in hw:
        by_class.setdefault(component.class_, []).append(component)

    return {
        "asset": asset, "software": software,
        "software_present": [s for s in software if s.present],
        "software_absent": [s for s in software if not s.present],
        "hardware": by_class, "users": users, "security": security,
        "interfaces": interfaces, "reports": reports, "events": events, "sources": sources,
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

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    trend_rows = (await session.execute(
        select(func.date_trunc("hour", SoftwareReport.received_at).label("hour"),
               func.count(SoftwareReport.id))
        .where(SoftwareReport.received_at >= since)
        .group_by("hour").order_by("hour")
    )).all()

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
        "reports_trend": [{"hour": hour.isoformat(), "count": count}
                          for hour, count in trend_rows],
        "recent_events": [{"event": ev.event, "at": ev.at.isoformat(),
                           "name": name, "hostname": hostname,
                           "software_id": str(ev.software_id) if ev.software_id else None}
                          for ev, name, hostname in recent_events],
    }


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


async def list_tokens(session: AsyncSession) -> list[EnrollmentToken]:
    return (await session.execute(
        select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc()).limit(20)
    )).scalars().all()