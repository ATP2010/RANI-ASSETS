"""Mesin scan SNMP: perluas range IP, probe perangkat, simpan hasil + asset.

Alur (gaya Lansweeper Scanning Targets + Custom OID Scanning):
1. Grup IP (`scan_groups`) berisi daftar CIDR/range + community (terenkripsi).
2. Setiap host di-probe: sysObjectID → sysDescr/sysName/sysUpTime/ifNumber →
   entity MIB (serial/model/vendor) → custom OID (`scan_oids`, diffilter vendor/model).
3. Hasil masuk `scan_results`; perangkat yang menjawab SNMP di-upsert sebagai
   asset `asset_type='network'` (identity: serial → hostname → IP, hanya untuk asset network).
4. Progres dipublikasikan ke WebSocket (`scan.progress`, `scan.done`).
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import decrypt_secret
from app.db import SessionLocal
from app.models import Asset, ScanGroup, ScanOid, ScanResult, ScanRun
from app.snmp import (ENTITY_MODEL, ENTITY_SERIAL, ENTITY_VENDOR, IF_NUMBER, SYS_DESCR,
                      SYS_NAME, SYS_OBJECT_ID, SYS_UPTIME, SnmpClient, SnmpError)
from app.ws import publish

log = logging.getLogger("rani.scan")
settings = get_settings()

VENDOR_BY_OID = {
    "1.3.6.1.4.1.9": "Cisco",
    "1.3.6.1.4.1.11": "HP",
    "1.3.6.1.4.1.311": "Microsoft",
    "1.3.6.1.4.1.2636": "Juniper",
    "1.3.6.1.4.1.890": "ZyXEL",
    "1.3.6.1.4.1.2011": "Huawei",
    "1.3.6.1.4.1.6486": "Alcatel-Lucent",
    "1.3.6.1.4.1.4526": "Netgear",
    "1.3.6.1.4.1.12356": "Fortinet",
    "1.3.6.1.4.1.14988": "MikroTik",
    "1.3.6.1.4.1.41112": "Ubiquiti",
    "1.3.6.1.4.1.25506": "H3C",
    "1.3.6.1.4.1.5089": "TP-Link",
}

_RUNNING: dict[str, str] = {}  # group_id -> run_id (cegah scan ganda per grup dalam proses ini)


class ScanError(RuntimeError):
    pass


# ------------------------------------------------------------------ range IP --
def normalize_range(value: str) -> str:
    """Validasi & normalisasi satu entri: CIDR, 'a-b', atau IP tunggal."""
    text = (value or "").strip()
    if not text:
        raise ScanError("range kosong")
    if "/" in text:
        try:
            net = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise ScanError(f"CIDR tidak valid: {text}") from exc
        if net.version != 4:
            raise ScanError(f"hanya IPv4: {text}")
        return str(net)
    if "-" in text:
        start_s, _, end_s = text.partition("-")
        try:
            start = ipaddress.ip_address(start_s.strip())
            end = ipaddress.ip_address(end_s.strip())
        except ValueError as exc:
            raise ScanError(f"range tidak valid: {text}") from exc
        if start.version != 4 or end.version != 4 or int(start) > int(end):
            raise ScanError(f"range tidak valid: {text}")
        return f"{start}-{end}"
    try:
        addr = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ScanError(f"IP tidak valid: {text}") from exc
    if addr.version != 4:
        raise ScanError(f"hanya IPv4: {text}")
    return str(addr)


def parse_ranges(values: list[str]) -> list[str]:
    out, seen = [], set()
    for raw in values:
        for line in str(raw).replace(",", "\n").splitlines():
            line = line.strip()
            if not line:
                continue
            item = normalize_range(line)
            if item not in seen:
                seen.add(item)
                out.append(item)
    if not out:
        raise ScanError("minimal satu range IP")
    return out


def expand_hosts(ranges: list[str], limit: int) -> tuple[list[str], bool]:
    """Kembalikan daftar host (maks `limit`) dan flag truncated."""
    hosts: list[str] = []
    seen: set[str] = set()
    for item in ranges:
        if item.count("-") == 1 and "/" not in item:
            start_s, _, end_s = item.partition("-")
            start, end = int(ipaddress.ip_address(start_s)), int(ipaddress.ip_address(end_s))
            candidates = (str(ipaddress.ip_address(n)) for n in range(start, end + 1))
        elif "/" in item:
            candidates = (str(ip) for ip in ipaddress.ip_network(item, strict=False).hosts())
        else:
            candidates = iter([item])
        for ip in candidates:
            if ip in seen:
                continue
            seen.add(ip)
            hosts.append(ip)
            if len(hosts) >= limit:
                return hosts, True
    return hosts, False


def guess_vendor(sys_object_id: str | None, sys_descr: str | None) -> str | None:
    oid = (sys_object_id or "").lstrip(".")
    for prefix, vendor in VENDOR_BY_OID.items():
        if oid.startswith(prefix + "."):
            return vendor
    if sys_descr:
        first = re.split(r"[\s,]", sys_descr.strip(), maxsplit=1)[0]
        if first and first.isalpha() and len(first) <= 24:
            return first
    return None


def guess_model(sys_descr: str | None, entity_model: str | None) -> str | None:
    if entity_model:
        return entity_model[:128]
    if not sys_descr:
        return None
    text = sys_descr.strip()
    match = re.search(r"\b(WS-C\d{4}[A-Z0-9-]*|C\d{4}[A-Z0-9-]*|N\d{4}[A-Z0-9-]*|"
                      r"SG\d{3}[A-Z0-9-]*|Catalyst\s+\S+|Nexus\s*\S+)\b", text, re.I)
    if match:
        return match.group(1)[:128]
    return text.splitlines()[0][:128]


# ---------------------------------------------------------------------- probe --
def probe_host(ip: str, *, community: str, version: int, port: int, timeout: float,
               retries: int, custom_oids: list[dict]) -> dict:
    """Probe satu IP (blocking; dipanggil via asyncio.to_thread)."""
    client = SnmpClient(ip, community, port=port, version=version,
                        timeout=timeout, retries=retries)
    base = client.get_many([SYS_OBJECT_ID, SYS_DESCR, SYS_NAME, SYS_UPTIME, IF_NUMBER])
    sys_oid = base.get(SYS_OBJECT_ID)
    if not sys_oid:
        raise SnmpError("tidak ada balasan SNMP")

    def first_walk(root: str, cap: int = 8) -> str | None:
        try:
            for vb in client.walk(root, max_rows=cap):
                if vb.value not in (None, ""):
                    return str(vb.value)
        except SnmpError:
            return None
        return None

    serial = first_walk(ENTITY_SERIAL, 6)
    entity_model = first_walk(ENTITY_MODEL, 6)
    entity_vendor = first_walk(ENTITY_VENDOR, 6)
    sys_descr = str(base.get(SYS_DESCR)).strip().strip('"') if base.get(SYS_DESCR) else None
    sys_name = base.get(SYS_NAME)
    vendor = (entity_vendor or guess_vendor(sys_oid, sys_descr) or "")[:96] or None

    oid_values: dict[str, object] = {}
    for item in custom_oids:
        label, oid = item["label"], item["oid"]
        if item.get("vendor") and (not vendor or
                                   item["vendor"].lower() not in vendor.lower()):
            continue
        if item.get("model"):
            model_now = guess_model(sys_descr, entity_model) or ""
            if item["model"].lower() not in model_now.lower():
                continue
        try:
            if oid.endswith(".*"):  # walk subtree (tabel), mis. ifDescr.*
                rows = client.walk(oid[:-2], max_rows=16)
                oid_values[label] = {vb.oid.rsplit(".", 1)[-1]: vb.value for vb in rows}
            else:
                value = client.get(oid)
                if value is not None:
                    oid_values[label] = value
        except SnmpError as exc:
            oid_values[label] = f"(error: {exc})"

    return {
        "ip": ip,
        "status": "ok",
        "sys_object_id": str(sys_oid)[:191] if sys_oid else None,
        "sys_name": (str(sys_name)[:191] if sys_name else None),
        "sys_descr": (sys_descr or None),
        "vendor": vendor,
        "model": guess_model(sys_descr, entity_model),
        "serial": (str(serial)[:128] if serial else None),
        "uptime_s": int(base.get(SYS_UPTIME) // 100) if isinstance(base.get(SYS_UPTIME), int) else None,
        "if_count": base.get(IF_NUMBER) if isinstance(base.get(IF_NUMBER), int) else None,
        "oid_values": oid_values,
    }


# ------------------------------------------------------------------ asset upsert --
async def upsert_network_asset(session: AsyncSession, result: dict) -> tuple[uuid.UUID | None, str]:
    """Cari/ buat asset network. Kembalikan (asset_id, 'new'|'update'|'skip')."""
    serial = result.get("serial")
    hostname = result.get("sys_name") or result.get("ip")
    asset = None
    if serial:
        asset = (await session.execute(
            select(Asset).where(Asset.serial == serial, Asset.asset_type == "network")
        )).scalar_one_or_none()
    if asset is None and hostname:
        asset = (await session.execute(
            select(Asset).where(Asset.hostname == hostname, Asset.asset_type == "network")
        )).scalar_one_or_none()
    if asset is None:
        asset = (await session.execute(
            select(Asset).where(Asset.ip_last == result["ip"], Asset.asset_type == "network")
        )).scalar_one_or_none()

    snmp_attrs = {
        "sys_object_id": result.get("sys_object_id"),
        "sys_descr": (result.get("sys_descr") or "")[:2000],
        "uptime_s": result.get("uptime_s"),
        "if_count": result.get("if_count"),
        "oid_values": result.get("oid_values") or {},
        "run_id": result.get("run_id"),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    created = asset is None
    if created:
        asset = Asset(asset_type="network", hostname=hostname, serial=serial,
                      vendor=result.get("vendor"), model=result.get("model"),
                      ip_last=result["ip"], status="online",
                      attrs={"snmp": snmp_attrs, "source": "snmp"})
        session.add(asset)
    else:
        asset.hostname = hostname or asset.hostname
        asset.serial = serial or asset.serial
        asset.vendor = result.get("vendor") or asset.vendor
        asset.model = result.get("model") or asset.model
        asset.ip_last = result["ip"]
        asset.status = "online"
        asset.last_seen = datetime.now(timezone.utc)
        attrs = dict(asset.attrs or {})
        attrs["snmp"] = snmp_attrs
        attrs["source"] = "snmp"
        asset.attrs = attrs
    await session.flush()
    return asset.id, ("new" if created else "update")


# --------------------------------------------------------------------- run scan --
async def _load_group(session: AsyncSession, group_id: uuid.UUID) -> tuple[ScanGroup, str]:
    group = (await session.execute(
        select(ScanGroup).where(ScanGroup.id == group_id))).scalar_one_or_none()
    if group is None:
        raise ScanError("grup scan tidak ditemukan")
    if not group.enabled:
        raise ScanError("grup scan nonaktif")
    if not group.community_enc:
        raise ScanError("community SNMP belum diisi untuk grup ini")
    try:
        community = decrypt_secret(group.community_enc, settings.RANI_INGEST_PEPPER)
    except ValueError as exc:
        raise ScanError("community tidak bisa didekripsi (pepper berubah?)") from exc
    return group, community


async def execute_scan(run_id: uuid.UUID) -> None:
    """Jalankan scan untuk satu ScanRun. Dipanggil sebagai background task."""
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    group_key = ""
    try:
        async with SessionLocal() as session:
            run = (await session.execute(
                select(ScanRun).where(ScanRun.id == run_id))).scalar_one_or_none()
            if run is None:
                return
            group, community = await _load_group(session, run.group_id)
            group_key = str(group.id)
            custom = [{"label": o.label, "oid": o.oid, "vendor": o.vendor, "model": o.model}
                      for o in (await session.execute(
                          select(ScanOid).where(ScanOid.enabled.is_(True))
                      )).scalars().all()]
            hosts, truncated = expand_hosts(group.ranges, settings.RANI_SCAN_MAX_HOSTS)
            run.hosts_total = len(hosts)
            run.stats = {"truncated": truncated, "group": group.name,
                         "ranges": group.ranges}
            await session.commit()
            await publish(redis, {"type": "scan.progress", "run_id": str(run_id),
                                  "group": group.name, "done": 0, "total": len(hosts),
                                  "found": 0})

            semaphore = asyncio.Semaphore(settings.RANI_SCAN_CONCURRENCY)
            done = found = 0
            cancelled = False

            async def one(ip: str) -> dict | None:
                async with semaphore:
                    try:
                        return await asyncio.to_thread(
                            probe_host, ip, community=community,
                            version=1 if group.snmp_version == "1" else 2,
                            port=group.port or 161, timeout=settings.RANI_SCAN_TIMEOUT_S,
                            retries=settings.RANI_SCAN_RETRIES, custom_oids=custom)
                    except SnmpError as exc:
                        return {"ip": ip, "status": "timeout", "error": str(exc)[:255]}
                    except Exception as exc:  # noqa: BLE001
                        log.warning("probe %s gagal: %s", ip, exc)
                        return {"ip": ip, "status": "error", "error": str(exc)[:255]}

            tasks = [asyncio.create_task(one(ip)) for ip in hosts]
            pending_events: list[dict] = []
            for task in asyncio.as_completed(tasks):
                outcome = await task
                done += 1
                if outcome and outcome.get("status") == "ok":
                    found += 1
                    outcome["run_id"] = str(run_id)
                    asset_id, action = await upsert_network_asset(session, outcome)
                    outcome["asset_id"] = asset_id
                    pending_events.append({
                        "type": "asset.new" if action == "new" else "asset.update",
                        "hostname": outcome.get("sys_name") or outcome["ip"],
                        "os": outcome.get("vendor") or "network device",
                        "source": "snmp"})
                session.add(ScanResult(run_id=run_id, ip=outcome["ip"],
                                       status=outcome.get("status", "error"),
                                       sys_object_id=outcome.get("sys_object_id"),
                                       sys_name=outcome.get("sys_name"),
                                       sys_descr=outcome.get("sys_descr"),
                                       vendor=outcome.get("vendor"),
                                       model=outcome.get("model"),
                                       serial=outcome.get("serial"),
                                       uptime_s=outcome.get("uptime_s"),
                                       if_count=outcome.get("if_count"),
                                       oid_values=outcome.get("oid_values") or {},
                                       error=outcome.get("error"),
                                       asset_id=outcome.get("asset_id")))
                run.hosts_done = done
                run.hosts_found = found
                if done % 5 == 0 or done == len(hosts):
                    await session.commit()
                    for event in pending_events:
                        await publish(redis, event)
                    pending_events.clear()
                    await publish(redis, {"type": "scan.progress", "run_id": str(run_id),
                                          "group": group.name, "done": done,
                                          "total": len(hosts), "found": found})
                if done % 8 == 0:
                    status = (await session.execute(
                        select(ScanRun.status).where(ScanRun.id == run_id))).scalar_one()
                    if status == "cancelled":
                        cancelled = True
                        for pending in tasks:
                            pending.cancel()
                        break

            run.status = "cancelled" if cancelled else "done"
            run.finished_at = datetime.now(timezone.utc)
            run.hosts_done = done
            run.hosts_found = found
            group.last_scan_at = datetime.now(timezone.utc)
            group.last_scan_status = f"{run.status}: {found}/{done}"
            await session.commit()
            await publish(redis, {"type": "scan.done", "run_id": str(run_id),
                                  "group": group.name, "status": run.status,
                                  "done": done, "total": len(hosts), "found": found})
    except asyncio.CancelledError:
        await _mark(run_id, "cancelled", "dibatalkan")
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("scan gagal: %s", exc)
        await _mark(run_id, "failed", str(exc)[:500])
        try:
            await publish(redis, {"type": "scan.done", "run_id": str(run_id),
                                  "status": "failed", "error": str(exc)[:200]})
        except Exception:
            pass
    finally:
        if group_key:
            _RUNNING.pop(group_key, None)
        await redis.aclose()


async def _mark(run_id: uuid.UUID, status: str, error: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ScanRun).where(ScanRun.id == run_id)
            .values(status=status, error=error, finished_at=datetime.now(timezone.utc)))
        await session.commit()


def register_run(group_id: uuid.UUID, run_id: uuid.UUID) -> None:
    _RUNNING[str(group_id)] = str(run_id)


def running_for(group_id: uuid.UUID) -> str | None:
    return _RUNNING.get(str(group_id))