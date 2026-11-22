"""Penjadwal scan SNMP otomatis per grup IP (menu Agents → Groups).

Dua mode:
- ``interval``: setiap N menit (UI boleh memasukkan jam, dikonversi ke menit).
- ``time``: pada jam ``HH:MM`` untuk hari-hari terpilih (kosong = setiap hari).

Loop berjalan di proses API. Karena ``uvicorn --workers 2`` menjalankan lifespan
di tiap worker, pemilihan grup due memakai ``FOR UPDATE SKIP LOCKED`` supaya satu
grup tidak pernah dijalankan dua kali.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import ScanGroup
from app.scanner import create_scan_run, find_running_run, launch_scan

log = logging.getLogger("rani.schedule")
settings = get_settings()

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@lru_cache
def schedule_zone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.RANI_SCHEDULE_TZ)
    except Exception:  # noqa: BLE001 — TZ tidak valid di env
        return ZoneInfo("Asia/Jakarta")


def parse_schedule_time(value: str | None) -> tuple[int, int] | None:
    """'HH:MM' -> (jam, menit); None kalau tidak valid."""
    match = _TIME_RE.match((value or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_schedule_days(value: str | None) -> set[int]:
    """'1,3,5' -> {1,3,5} (ISO 1=Senin..7=Minggu). Kosong = semua hari."""
    days: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part))
    return days


def compute_next_run(group: ScanGroup, now: datetime | None = None) -> datetime | None:
    """Hitung jadwal berikutnya (UTC). None kalau jadwal nonaktif."""
    if not getattr(group, "schedule_enabled", False):
        return None
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    local = base.astimezone(schedule_zone())

    if (group.schedule_mode or "interval").lower() == "interval":
        minutes = int(group.schedule_interval_min or 0)
        minutes = max(settings.RANI_SCAN_SCHEDULE_MIN_INTERVAL_MIN, minutes)
        return (local + timedelta(minutes=minutes)).astimezone(timezone.utc)

    hour, minute = parse_schedule_time(group.schedule_time) or (0, 0)
    days = parse_schedule_days(group.schedule_days)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    for _ in range(8):  # maksimal lewat 1 minggu
        if not days or candidate.isoweekday() in days:
            return candidate.astimezone(timezone.utc)
        candidate += timedelta(days=1)
    return None


async def claim_due_groups(session: AsyncSession, limit: int = 20) -> list[ScanGroup]:
    """Ambil grup yang jatuh tempo dan kunci barisnya (aman untuk multi-worker)."""
    rows = await session.execute(
        select(ScanGroup)
        .where(ScanGroup.schedule_enabled.is_(True),
               ScanGroup.enabled.is_(True),
               ScanGroup.next_run_at.is_not(None),
               ScanGroup.next_run_at <= func.now())
        .order_by(ScanGroup.next_run_at)
        .with_for_update(skip_locked=True)
        .limit(limit))
    return list(rows.scalars().all())


async def run_due_scans() -> int:
    """Jalankan semua scan yang jatuh tempo. Return jumlah scan yang dimulai."""
    started = 0
    async with SessionLocal() as session:
        groups = await claim_due_groups(session)
        if not groups:
            return 0
        now = datetime.now(timezone.utc)
        for group in groups:
            try:
                run = None
                if await find_running_run(session, group.id) is None:
                    run = await create_scan_run(
                        session, group, actor="scheduler",
                        action="scan.schedule.trigger",
                        details={"mode": group.schedule_mode,
                                 "schedule_time": group.schedule_time,
                                 "schedule_days": group.schedule_days,
                                 "interval_min": group.schedule_interval_min})
                group.next_run_at = compute_next_run(group, now)
                if run is not None:
                    group.last_schedule_at = now
                await session.commit()
                if run is not None:
                    launch_scan(run)
                    started += 1
                    log.info("scan terjadwal dimulai: grup %r (run %s)",
                             group.name, run.id)
            except Exception:  # noqa: BLE001 — satu grup gagal jangan hentikan lainnya
                await session.rollback()
                log.exception("gagal menjadwalkan scan grup %r", group.name)
                # Tetap majukan jadwal agar tidak retry tiap tick.
                async with SessionLocal() as fix:
                    row = await fix.get(ScanGroup, group.id)
                    if row is not None:
                        row.next_run_at = compute_next_run(row, now)
                        await fix.commit()
    return started


async def scan_schedule_loop() -> None:
    """Loop penjadwal; dipanggil dari lifespan API."""
    await asyncio.sleep(5)
    while True:
        try:
            count = await run_due_scans()
            if count:
                log.info("scan scheduler memulai %d scan", count)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("scan scheduler loop gagal")
        await asyncio.sleep(max(5, int(settings.RANI_SCAN_SCHEDULER_TICK_S)))
