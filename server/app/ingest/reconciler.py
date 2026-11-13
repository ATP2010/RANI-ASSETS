"""Reconciler: payload raniPush → asset, delta software, komponen, security.

Aturan identitas (DEVGUIDE §4.2): machine_id → serial → MAC → hostname.
IP hanya atribut, tidak pernah jadi kunci.
"""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.models import (Asset, AssetSource, HwComponent, NetworkInterface, SecurityState,
                        Software, SoftwareEvent, SoftwareReport, UserSeen)
from app.ws import publish

log = logging.getLogger("rani.reconciler")

JUNK_IDENTIFIERS = {
    "", "default string", "to be filled by o.e.m.", "to be filled by oem", "none", "n/a",
    "na", "unknown", "not specified", "system serial number", "0", "00000000", "0000000000",
}


def clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_identifier(value) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return None if text.lower() in JUNK_IDENTIFIERS else text


def norm_software(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())[:255]


def normalize_mac(value) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    hexdigits = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(hexdigits) != 12:
        return None
    mac = ":".join(hexdigits[i:i + 2] for i in range(0, 12, 2)).lower()
    if mac in {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}:
        return None
    return mac


def pick_primary_interface(interfaces: list[dict]) -> dict | None:
    usable = [i for i in interfaces if i.get("mac") and normalize_mac(i.get("mac"))]
    if not usable:
        return usable[0] if usable else None

    def score(item: dict) -> tuple:
        name = (item.get("name") or "").lower()
        virtual = any(hint in name for hint in ("docker", "veth", "br-", "virbr", "vmnet",
                                                "loopback", "lo", "tun", "tap", "vboxnet"))
        return (bool(item.get("gateway")), bool(item.get("ipv4")), not virtual,
                not name.startswith(("lo", "docker")))

    return max(usable, key=score)


def _iso(value) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _match_asset(session: AsyncSession, machine_id: str | None, serial: str | None,
                       mac: str | None, hostname: str | None) -> tuple[Asset | None, str]:
    """Identity match berjenjang machine_id → serial → MAC → hostname.

    Konflik eksplisit: kandidat yang punya `machine_id` berbeda TIDAK boleh di-merge
    lewat serial/MAC/hostname (mis. imaging ulang, snapshot VM, payload uji dengan MAC
    yang sama). machine_id adalah kunci otoritatif bila tersedia.
    """
    checks = (("machine_id", machine_id), ("serial", serial),
              ("primary_mac", mac), ("hostname", hostname))
    for field, value in checks:
        if not value:
            continue
        asset = (await session.execute(
            select(Asset).where(getattr(Asset, field) == value).limit(1)
        )).scalar_one_or_none()
        if asset is None:
            continue
        if (field != "machine_id" and machine_id and asset.machine_id
                and asset.machine_id != machine_id):
            log.warning("kandidat %s cocok via %s tapi machine_id berbeda (%s != %s) — "
                        "dibuat asset baru", asset.id, field, asset.machine_id, machine_id)
            return None, "new"
        return asset, field
    return None, "new"


async def process_report(session: AsyncSession, redis: Redis, report: SoftwareReport) -> Asset:
    payload = report.raw or {}
    identity = payload.get("identity") or {}
    hardware = payload.get("hardware") or {}
    os_info = payload.get("os") or {}
    network = payload.get("network") or {}
    users = payload.get("users") or {}
    security = payload.get("security") or {}

    machine_id = clean_identifier(identity.get("machine_id"))
    hostname = clean_text(identity.get("hostname"))
    interfaces = [i for i in (network.get("interfaces") or []) if isinstance(i, dict)]
    primary_if = pick_primary_interface(interfaces)
    mac = normalize_mac(primary_if.get("mac")) if primary_if else None
    serial = clean_identifier(hardware.get("serial"))

    collected_at = _iso(payload.get("collected_at")) or datetime.now(timezone.utc)

    asset, matched_on = await _match_asset(session, machine_id, serial, mac, hostname)
    is_new = asset is None

    if asset is None:
        asset = Asset(first_seen=collected_at, last_seen=collected_at, status="online")
        session.add(asset)
        await session.flush()

    # --- identitas & atribut dasar ---
    asset.asset_type = "computer"
    asset.hostname = hostname or asset.hostname
    asset.domain = clean_text(identity.get("domain")) or asset.domain
    asset.machine_id = machine_id or asset.machine_id
    asset.serial = serial or asset.serial
    asset.vendor = clean_text(hardware.get("vendor")) or asset.vendor
    asset.model = clean_text(hardware.get("model")) or asset.model
    asset.os_family = clean_text(os_info.get("family")) or asset.os_family
    asset.os_caption = clean_text(os_info.get("caption")) or asset.os_caption
    asset.os_version = clean_text(os_info.get("version")) or asset.os_version
    asset.os_build = clean_text(os_info.get("build")) or asset.os_build
    asset.primary_mac = mac or asset.primary_mac
    if primary_if and primary_if.get("ipv4"):
        asset.ip_last = clean_text(primary_if.get("ipv4")) or asset.ip_last
    asset.last_seen = collected_at
    asset.status = "online"
    asset.agent_id = report.agent_id
    attrs = dict(asset.attrs or {})
    attrs.update({
        "bios_version": clean_text(hardware.get("bios_version")),
        "bios_date": clean_text(hardware.get("bios_date")),
        "chassis_type": clean_text(hardware.get("chassis_type")),
        "domain_joined": identity.get("domain_joined"),
        "os_install_date": clean_text(os_info.get("install_date")),
        "uptime_s": os_info.get("uptime_s"),
        "last_agent_version": clean_text(payload.get("agent_version")),
    })
    asset.attrs = {k: v for k, v in attrs.items()}

    session.add(AssetSource(
        asset_id=asset.id, source="agent", matched_on=matched_on,
        confidence=1.0 if matched_on in ("machine_id", "serial") else 0.8,
        evidence={"report_id": str(report.id), "hostname": hostname,
                  "machine_id": machine_id, "serial": serial, "mac": mac},
        ts=datetime.now(timezone.utc),
    ))

    # --- delta software ---
    incoming: dict[str, dict] = {}
    for item in payload.get("software") or []:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("name"))
        if not name:
            continue
        key = norm_software(name)
        current = incoming.get(key)
        version = clean_text(item.get("version"))
        if current is None or (version and not current.get("version")):
            incoming[key] = {"name": name, "version": version,
                             "vendor": clean_text(item.get("vendor")),
                             "install_date": clean_text(item.get("install_date")),
                             "source": clean_text(item.get("source"))}

    existing_rows = (await session.execute(
        select(Software).where(Software.asset_id == asset.id)
    )).scalars().all()
    existing = {row.name_norm: row for row in existing_rows}
    existing_present = [row for row in existing_rows if row.present]
    skipped_uninstall = False
    now = datetime.now(timezone.utc)
    installed = changed = uninstalled = 0

    for key, item in incoming.items():
        row = existing.get(key)
        if row is None:
            row = Software(asset_id=asset.id, name_norm=key, name_raw=item["name"],
                           version=item["version"], vendor=item["vendor"],
                           install_date=item["install_date"], source=item["source"],
                           present=True, first_seen=now, last_seen=now)
            session.add(row)
            await session.flush()
            session.add(SoftwareEvent(asset_id=asset.id, software_id=row.id,
                                      event="installed", at=now,
                                      detail={"name": item["name"], "version": item["version"]}))
            installed += 1
            continue
        if item["version"] and row.version and item["version"] != row.version:
            session.add(SoftwareEvent(asset_id=asset.id, software_id=row.id, event="changed",
                                      at=now, detail={"from": row.version, "to": item["version"],
                                                      "name": item["name"]}))
            changed += 1
        row.name_raw = item["name"]
        row.version = item["version"] or row.version
        row.vendor = item["vendor"] or row.vendor
        row.install_date = item["install_date"] or row.install_date
        row.source = item["source"] or row.source
        row.present = True
        row.last_seen = now

    for key, row in existing.items():
        if key in incoming or not row.present:
            continue
        # Guard: penurunan drastis = kemungkinan koleksi software gagal (timeout registry/
        # dpkg), bukan uninstall massal. Jangan flip present, cukup catat di log.
        if len(existing_present) > 10 and len(incoming) < 0.5 * len(existing_present):
            skipped_uninstall = True
            break
        row.present = False
        session.add(SoftwareEvent(asset_id=asset.id, software_id=row.id, event="uninstalled",
                                  at=now, detail={"name": row.name_raw, "version": row.version}))
        uninstalled += 1

    if skipped_uninstall:
        log.warning("software drop guard aktif untuk asset %s: incoming %d vs existing %d — "
                    "uninstall massal dilewati", asset.id, len(incoming), len(existing_present))
        report.error = (f"software drop guard: {len(incoming)} masuk vs {len(existing_present)} "
                       "tercatat — uninstall tidak diterapkan")

    # --- komponen hardware (upsert, yang hilang → present=false) ---
    hw_rows = {
        "cpu": [c for c in hardware.get("cpu") or [] if isinstance(c, dict)],
        "memory": [m for m in hardware.get("memory") or [] if isinstance(m, dict)],
        "disk": [d for d in hardware.get("disks") or [] if isinstance(d, dict)],
        "gpu": [g for g in hardware.get("gpu") or [] if isinstance(g, dict)],
        "monitor": [m for m in hardware.get("monitors") or [] if isinstance(m, dict)],
    }
    for cls, items in hw_rows.items():
        seen_keys: set[str] = set()
        for index, item in enumerate(items):
            identity_raw = (item.get("serial") or item.get("model") or item.get("name")
                            or f"idx-{index}")
            key = f"{identity_raw}"[:255]
            if key in seen_keys:
                key = f"{key}#{index}"
            seen_keys.add(key)
            comp = (await session.execute(
                select(HwComponent).where(HwComponent.asset_id == asset.id,
                                          HwComponent.class_ == cls,
                                          HwComponent.key == key)
            )).scalar_one_or_none()
            if comp is None:
                comp = HwComponent(asset_id=asset.id, class_=cls, key=key,
                                   first_seen=now, last_seen=now, present=True, attrs=item)
                session.add(comp)
            else:
                comp.attrs = item
                comp.present = True
                comp.last_seen = now
        if seen_keys:
            stale = (await session.execute(
                select(HwComponent).where(HwComponent.asset_id == asset.id,
                                          HwComponent.class_ == cls,
                                          HwComponent.present.is_(True),
                                          HwComponent.key.notin_(seen_keys))
            )).scalars().all()
            for comp in stale:
                comp.present = False

    # --- users ---
    user_entries: list[tuple[str, str]] = []
    primary_user = clean_text(users.get("primary"))
    if primary_user:
        user_entries.append((primary_user, "primary"))
    for name in users.get("logged_on") or []:
        text = clean_text(name)
        if text:
            user_entries.append((text, "logged_on"))
    for name in users.get("local_admins") or []:
        text = clean_text(name)
        if text:
            user_entries.append((text, "local_admin"))
    await session.execute(delete(UserSeen).where(UserSeen.asset_id == asset.id))
    for username, role in {(u.lower(), r): (u, r) for u, r in user_entries}.values():
        session.add(UserSeen(asset_id=asset.id, username=username[:191], role=role,
                             last_seen=now))

    # --- security state (history) ---
    session.add(SecurityState(
        asset_id=asset.id, checked_at=collected_at,
        av_product=clean_text(security.get("av_product")),
        av_ok=security.get("av_up_to_date"),
        firewall={"profiles_on": security.get("firewall_profiles_on") or []},
        disk_encryption=clean_text(security.get("disk_encryption")),
        tpm_version=clean_text(security.get("tpm_version")),
        secure_boot=security.get("secure_boot"),
        pending_reboot=security.get("pending_reboot"),
        payload=security,
    ))

    # --- network interfaces ---
    current_if_names: set[str] = set()
    for item in interfaces:
        name = clean_text(item.get("name")) or "unknown"
        current_if_names.add(name[:96])
        row = (await session.execute(
            select(NetworkInterface).where(NetworkInterface.asset_id == asset.id,
                                           NetworkInterface.name == name[:96])
        )).scalar_one_or_none()
        if row is None:
            row = NetworkInterface(asset_id=asset.id, name=name[:96], last_seen=now)
            session.add(row)
        row.mac = normalize_mac(item.get("mac")) or row.mac
        row.ipv4 = clean_text(item.get("ipv4")) or row.ipv4
        row.ipv6 = clean_text(item.get("ipv6")) or row.ipv6
        row.mask = clean_text(item.get("mask")) or row.mask
        row.gateway = clean_text(item.get("gateway")) or row.gateway
        row.dns = item.get("dns") or []
        row.dhcp = item.get("dhcp")
        row.speed_mbps = item.get("speed_mbps")
        row.present = True
        row.last_seen = now
    if current_if_names:
        stale_if = (await session.execute(
            select(NetworkInterface).where(NetworkInterface.asset_id == asset.id,
                                          NetworkInterface.present.is_(True),
                                          NetworkInterface.name.notin_(current_if_names))
        )).scalars().all()
        for row in stale_if:
            row.present = False

    report.asset_id = asset.id
    report.status = "processed"
    report.processed_at = now
    if not skipped_uninstall:
        report.error = None
    await session.flush()

    event = {
        "type": "asset.new" if is_new else "asset.update",
        "asset_id": str(asset.id),
        "hostname": asset.hostname,
        "os": asset.os_caption,
        "status": asset.status,
        "report_id": str(report.id),
        "software": {"installed": installed, "uninstalled": uninstalled, "changed": changed},
        "at": now.isoformat(),
    }
    await publish(redis, event)

    log.info("report %s → asset %s (%s) +%d/-%d/~%d software", report.id, asset.id,
             "new" if is_new else matched_on, installed, uninstalled, changed)
    return asset


async def mark_stale_assets(session: AsyncSession, redis: Redis, older_than_s: int) -> int:
    from datetime import timedelta

    threshold = datetime.now(timezone.utc) - timedelta(seconds=older_than_s)
    rows = (await session.execute(
        select(Asset).where(Asset.status == "online", Asset.last_seen < threshold)
    )).scalars().all()
    for asset in rows:
        asset.status = "offline"
        await publish(redis, {"type": "asset.offline", "asset_id": str(asset.id),
                              "hostname": asset.hostname,
                              "at": datetime.now(timezone.utc).isoformat()})
    await session.commit()
    return len(rows)