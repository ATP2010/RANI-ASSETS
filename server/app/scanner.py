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
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import get_settings
from app.crypto import decrypt_secret
from app.db import SessionLocal
from app.ingest.reconciler import normalize_mac
from app.models import Asset, EndpointPortMapping, ScanGroup, ScanOid, ScanResult, ScanRun
from app.snmp import (DOT1D_BASE_PORT_IFINDEX, DOT1D_TP_FDB_PORT,
                      DOT1D_TP_FDB_STATUS, DOT1Q_TP_FDB_PORT, DOT1Q_TP_FDB_STATUS,
                      DOT1Q_VLAN_FDB_ID, ENTITY_MODEL, ENTITY_SERIAL, ENTITY_VENDOR,
                      FDB_STATUS, IF_DESCR, IF_NAME, IF_NUMBER, SYS_DESCR, SYS_NAME,
                      SYS_OBJECT_ID, SYS_UPTIME, SnmpClient, SnmpError)
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
_TASKS: set[asyncio.Task] = set()


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


# ----------------------------------------------------------- bridge FDB (F2.4) --
def index_suffix(oid: str, base: str) -> list[int] | None:
    """Ambil bagian indeks dari OID tabel, mis. ...1.2.3.4.5.6 → [1,2,3,4,5,6]."""
    prefix = base.rstrip(".") + "."
    if not oid.startswith(prefix):
        return None
    parts = oid[len(prefix):].split(".")
    try:
        return [int(p) for p in parts if p != ""]
    except ValueError:
        return None


def parse_fdb_index(oid: str, base: str) -> tuple[int, str] | None:
    """Indeks tabel FDB → (vlan/fdb-id, mac).

    dot1dTpFdbPort:  <mac 6 oktet>              → vlan 0
    dot1qTpFdbPort:  <fdb-id>.<mac 6 oktet>     → vlan = fdb-id (dipetakan nanti)
    """
    parts = index_suffix(oid, base)
    if not parts or len(parts) not in (6, 7):
        return None
    octets = parts[-6:]
    if any(b < 0 or b > 255 for b in octets):
        return None
    if octets[0] & 0x01:          # bit multicast/broadcast → bukan MAC endpoint
        return None
    mac = ":".join(f"{b:02x}" for b in octets)
    if normalize_mac(mac) is None:      # zero MAC dsb.
        return None
    vlan = parts[0] if len(parts) == 7 else 0
    return vlan, mac


def _if_names(client: SnmpClient, cap: int = 512) -> dict[int, str]:
    """ifIndex → nama port. ifName (IF-MIB) dulu, fallback ifDescr."""
    for root in (IF_NAME, IF_DESCR):
        names: dict[int, str] = {}
        try:
            for vb in client.walk_bulk(root, max_rows=cap):
                idx = index_suffix(vb.oid, root)
                if idx and len(idx) == 1 and vb.value not in (None, ""):
                    names[idx[0]] = str(vb.value).strip()[:96]
        except SnmpError:
            continue
        if names:
            return names
    return {}


def _bridge_port_map(client: SnmpClient, cap: int = 512) -> dict[int, int]:
    """Bridge port number → ifIndex (dot1dBasePortIfIndex)."""
    out: dict[int, int] = {}
    try:
        for vb in client.walk_bulk(DOT1D_BASE_PORT_IFINDEX, max_rows=cap):
            idx = index_suffix(vb.oid, DOT1D_BASE_PORT_IFINDEX)
            if idx and len(idx) == 1 and isinstance(vb.value, int):
                out[idx[0]] = vb.value
    except SnmpError:
        pass
    return out


def _vlan_names(client: SnmpClient, cap: int = 128) -> dict[int, int]:
    """fdb-id → VLAN (dot1qVlanFdbId; di banyak switch fdb-id == VLAN id)."""
    out: dict[int, int] = {}
    try:
        for vb in client.walk_bulk(DOT1Q_VLAN_FDB_ID, max_rows=cap):
            idx = index_suffix(vb.oid, DOT1Q_VLAN_FDB_ID)
            if idx and len(idx) == 1 and isinstance(vb.value, int):
                out.setdefault(vb.value, idx[0])
    except SnmpError:
        pass
    return out


def collect_bridge_fdb(client: SnmpClient, max_rows: int = 2000) -> dict:
    """Baca tabel forwarding bridge: MAC → port switch.

    Coba BRIDGE-MIB (dot1d) dulu karena paling universal; kalau kosong pakai
    Q-BRIDGE-MIB (dot1q, VLAN-aware). Perangkat non-switch tidak menjawab → hasil kosong.
    """
    empty = {"kind": None, "rows": [], "count": 0, "truncated": False, "ports": 0}
    vlan_map: dict[int, int] | None = None
    for kind, port_oid, status_oid in (
            ("dot1d", DOT1D_TP_FDB_PORT, DOT1D_TP_FDB_STATUS),
            ("dot1q", DOT1Q_TP_FDB_PORT, DOT1Q_TP_FDB_STATUS)):
        try:
            port_rows = client.walk_bulk(port_oid, max_rows=max_rows)
        except SnmpError:
            continue
        if not port_rows:
            continue
        if kind == "dot1q" and vlan_map is None:
            vlan_map = _vlan_names(client)
        status_by_index: dict[tuple[int, ...], object] = {}
        try:
            for vb in client.walk_bulk(status_oid, max_rows=max_rows):
                idx = index_suffix(vb.oid, status_oid)
                if idx:
                    status_by_index[tuple(idx)] = vb.value
        except SnmpError:
            pass
        port_if = _bridge_port_map(client)
        if_names = _if_names(client)
        rows: list[dict] = []
        seen: set[tuple[int, str]] = set()
        for vb in port_rows:
            parsed = parse_fdb_index(vb.oid, port_oid)
            if parsed is None:
                continue
            vlan, mac = parsed
            if kind == "dot1q" and vlan_map:
                vlan = vlan_map.get(vlan, vlan)
            if (vlan, mac) in seen:
                continue
            try:
                bridge_port = int(vb.value)
            except (TypeError, ValueError):
                continue
            idx = index_suffix(vb.oid, port_oid)
            status_code = status_by_index.get(tuple(idx)) if idx else None
            status = FDB_STATUS.get(status_code, "learned") if isinstance(status_code, int) \
                else "learned"
            if status == "invalid":
                continue
            if_index = port_if.get(bridge_port)
            rows.append({
                "mac": mac,
                "vlan": vlan,
                "bridge_port": bridge_port,
                "if_index": if_index,
                "if_name": if_names.get(if_index) if if_index else None,
                "status": status,
            })
            seen.add((vlan, mac))
        return {
            "kind": kind,
            "rows": rows,
            "count": len(rows),
            # truncated bila tabel mentah menyentuh batas (masih ada baris tak terbaca)
            "truncated": len(port_rows) >= max_rows,
            "ports": len({r["if_name"] or r["bridge_port"] for r in rows}),
        }
    return empty


# ---------------------------------------------------------------------- probe --
def probe_host(ip: str, *, community: str, version: int, port: int, timeout: float,
               retries: int, custom_oids: list[dict], collect_fdb: bool = True,
               fdb_max: int = 2000) -> dict:
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

    bridge = {"kind": None, "rows": [], "count": 0, "truncated": False, "ports": 0}
    if collect_fdb:
        # Data port map tidak boleh menggagalkan scan: device lambat / tabel rusak = kosong.
        try:
            bridge = collect_bridge_fdb(client, max_rows=fdb_max)
        except SnmpError as exc:
            bridge["error"] = str(exc)[:200]
        except Exception as exc:  # noqa: BLE001
            log.warning("port map %s gagal: %s", ip, exc)
            bridge["error"] = str(exc)[:200]

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
        "bridge": bridge,
        "fdb": bridge["rows"],
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
    bridge = result.get("bridge") or {}
    if bridge.get("kind"):
        # FDB mentah tidak disimpan di attrs (bisa ribuan baris) — hanya ringkasan.
        # Detail MAC↔port ada di tabel endpoint_port_mappings.
        snmp_attrs["bridge"] = {
            "kind": bridge.get("kind"),
            "count": bridge.get("count", 0),
            "ports": bridge.get("ports", 0),
            "truncated": bool(bridge.get("truncated")),
            "error": bridge.get("error"),
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


async def upsert_port_mappings(session: AsyncSession, asset_id: uuid.UUID,
                               run_id: uuid.UUID | None, rows: list[dict]) -> dict:
    """Upsert MAC↔port untuk satu switch; MAC hilang → `present=false` (bukan dihapus).

    `endpoint_asset_id` diisi bila MAC cocok dengan `assets.primary_mac` yang sudah ada.
    TIDAK membuat asset baru dari FDB — FDB hanya membuktikan MAC ada di port, bukan
    identitas lengkap (aturan DEVGUIDE §4.2).
    """
    if not rows:
        return {"inserted": 0, "updated": 0, "stale": 0, "linked": 0}
    now = datetime.now(timezone.utc)
    existing = (await session.execute(
        select(EndpointPortMapping)
        .where(EndpointPortMapping.switch_asset_id == asset_id))).scalars().all()
    by_key = {(row.vlan, row.mac): row for row in existing}

    macs = sorted({r["mac"] for r in rows if r.get("mac")})
    endpoint_by_mac: dict[str, uuid.UUID] = {}
    if macs:
        for aid, pmac in (await session.execute(
                select(Asset.id, Asset.primary_mac)
                .where(func.lower(Asset.primary_mac).in_(macs),
                       Asset.id != asset_id))).all():
            if pmac:
                endpoint_by_mac[pmac.lower()] = aid

    seen: set[tuple[int, str]] = set()
    inserted = updated = 0
    for item in rows:
        mac = item.get("mac")
        if not mac:
            continue
        key = (int(item.get("vlan") or 0), mac)
        if key in seen:
            continue
        seen.add(key)
        obj = by_key.get(key)
        if obj is None:
            obj = EndpointPortMapping(switch_asset_id=asset_id, run_id=run_id,
                                      vlan=key[0], mac=key[1], first_seen=now)
            session.add(obj)
            inserted += 1
        else:
            obj.run_id = run_id or obj.run_id
            updated += 1
        bridge_port = item.get("bridge_port")
        obj.bridge_port = int(bridge_port) if bridge_port is not None else None
        if_index = item.get("if_index")
        obj.if_index = int(if_index) if if_index is not None else None
        obj.if_name = (item.get("if_name") or None)
        obj.status = item.get("status") or "learned"
        obj.endpoint_asset_id = endpoint_by_mac.get(mac)
        obj.present = True
        obj.last_seen = now

    stale = 0
    for key, obj in by_key.items():
        if key not in seen and obj.present:
            obj.present = False
            stale += 1
    await session.flush()
    return {"inserted": inserted, "updated": updated, "stale": stale,
            "linked": len(endpoint_by_mac)}


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
            fdb_rows = bridges = 0
            cancelled = False

            async def one(ip: str) -> dict | None:
                async with semaphore:
                    try:
                        return await asyncio.to_thread(
                            probe_host, ip, community=community,
                            version=1 if group.snmp_version == "1" else 2,
                            port=group.port or 161, timeout=settings.RANI_SCAN_TIMEOUT_S,
                            retries=settings.RANI_SCAN_RETRIES, custom_oids=custom,
                            collect_fdb=bool(settings.RANI_SCAN_FDB_ENABLED
                                             and group.fdb_enabled),
                            fdb_max=settings.RANI_SCAN_FDB_MAX)
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
                    if asset_id is not None and outcome.get("fdb"):
                        mapping = await upsert_port_mappings(session, asset_id, run_id,
                                                             outcome["fdb"])
                        outcome["fdb_count"] = mapping["inserted"] + mapping["updated"]
                        fdb_rows += outcome["fdb_count"] or 0
                        bridges += 1
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
                                       fdb_count=outcome.get("fdb_count"),
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
            stats = dict(run.stats or {})
            stats.update({"bridges": bridges, "port_map_rows": fdb_rows})
            run.stats = stats
            group.last_scan_at = datetime.now(timezone.utc)
            group.last_scan_status = f"{run.status}: {found}/{done}"
            await session.commit()
            await publish(redis, {"type": "scan.done", "run_id": str(run_id),
                                  "group": group.name, "status": run.status,
                                  "done": done, "total": len(hosts), "found": found,
                                  "bridges": bridges, "port_map_rows": fdb_rows})
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


async def find_running_run(session: AsyncSession, group_id: uuid.UUID,
                           max_age_h: int = 6) -> ScanRun | None:
    """Run 'running' yang masih dianggap hidup (bukan sisa proses yang mati)."""
    rows = (await session.execute(
        select(ScanRun).where(ScanRun.group_id == group_id,
                              ScanRun.status == "running")
        .order_by(ScanRun.started_at.desc()).limit(20))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.started_at is not None and row.started_at > now - timedelta(hours=max_age_h):
            return row
    return None


async def create_scan_run(session: AsyncSession, group: ScanGroup, *,
                          actor: str | None, request=None,
                          action: str = "scan.start",
                          details: dict | None = None) -> ScanRun:
    """Buat baris ScanRun + audit. Belum commit dan belum dijalankan."""
    run = ScanRun(group_id=group.id, status="running", created_by=actor,
                  stats={"group": group.name})
    session.add(run)
    await session.flush()
    await audit(session, request, actor=actor, action=action,
                target=str(run.id),
                details={"group": group.name, "ranges": group.ranges,
                         **(details or {})})
    return run


def launch_scan(run: ScanRun) -> None:
    """Daftarkan run in-process lalu jalankan sebagai background task."""
    register_run(run.group_id, run.id)
    task = asyncio.create_task(execute_scan(run.id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def start_group_scan(session: AsyncSession, group: ScanGroup, *,
                           actor: str | None, request=None,
                           action: str = "scan.start",
                           details: dict | None = None) -> ScanRun | None:
    """Mulai scan satu grup. Return None kalau grup sudah punya run 'running'."""
    if await find_running_run(session, group.id):
        return None
    run = await create_scan_run(session, group, actor=actor, request=request,
                                action=action, details=details)
    await session.commit()
    launch_scan(run)
    return run


async def mark_interrupted_runs(session: AsyncSession, max_age_min: int = 10) -> int:
    """Tandai run 'running' sisa proses lama (server restart) sebagai failed."""
    now = datetime.now(timezone.utc)
    rows = (await session.execute(select(ScanRun).where(ScanRun.status == "running"))).scalars().all()
    stale = [r for r in rows
             if r.started_at is not None and r.started_at < now - timedelta(minutes=max_age_min)]
    for row in stale:
        row.status = "failed"
        row.error = "interrupted (server restart)"
        row.finished_at = now
    if stale:
        await session.commit()
    return len(stale)