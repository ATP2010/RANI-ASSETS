#!/usr/bin/env python3
"""raniPush — collector + pusher inventory RANI (Windows/Linux, stdlib-first).

Pemakaian:
    raniPush --enroll <token> <server[:port]>     # sekali per PC, simpan signing key
    raniPush <server[:port]>                       # collect + push (dipakai Task Scheduler)
    raniPush --collect                             # cetak payload JSON ke stdout
    raniPush --from-file payload.json <server>     # kirim payload yang sudah ada

Exit code: 0 = sukses / terspool (dicoba lagi pada jadwal berikutnya), 1 = gagal fatal.

Konfigurasi: %PROGRAMDATA%\\Rani\\config.json (Windows) atau /etc/rani/config.json
(atau ~/.rani/config.json bila tidak writable). Spool offline di direktori yang sama.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

AGENT_VERSION = "0.1.0"
SCHEMA_VERSION = 1
IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------- paths
def config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Rani"
    else:
        candidate = Path("/etc/rani")
        base = candidate if os.access(candidate.parent, os.W_OK) else Path.home() / ".rani"
    base.mkdir(parents=True, exist_ok=True)
    return base


CONFIG_PATH = config_dir() / "config.json"
SPOOL_DIR = config_dir() / "spool"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if not IS_WINDOWS:
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass


# ----------------------------------------------------------------------- helpers
def run(cmd: list[str], timeout: int = 25) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              errors="replace")
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def ps_json(script: str):
    """Jalankan PowerShell dan parse JSON. None bila PowerShell tidak ada/gagal."""
    if not IS_WINDOWS:
        return None
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-Command", script]
    out = run(cmd, timeout=60)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def mac_normalize(value) -> str | None:
    digits = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(digits) != 12:
        return None
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2)).lower()


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# --------------------------------------------------------------------- Windows
def collect_windows() -> dict:
    identity = {"machine_id": None, "hostname": socket.gethostname(), "domain": None,
                "domain_joined": None}

    try:
        import winreg  # noqa: PLC0415
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | 0x0100) as key:
            identity["machine_id"] = clean(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        pass
    if not identity["machine_id"]:
        identity["machine_id"] = clean(run(["wmic", "csproduct", "get", "UUID"]) or "") or None

    cs = ps_json("Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,"
                 "Domain,PartOfDomain,TotalPhysicalMemory | ConvertTo-Json -Compress")
    cs = cs if isinstance(cs, dict) else {}
    product = ps_json("Get-CimInstance Win32_ComputerSystemProduct | Select-Object Vendor,"
                      "Name,IdentifyingNumber | ConvertTo-Json -Compress") or {}
    bios = ps_json("Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion,ReleaseDate "
                   "| ConvertTo-Json -Compress") or {}
    os_row = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,"
                     "BuildNumber,InstallDate,OSArchitecture,LastBootUpTime,LocalDateTime,"
                     "Locale,TotalVisibleMemorySize | ConvertTo-Json -Compress") or {}

    identity["domain"] = clean(cs.get("Domain"))
    identity["domain_joined"] = cs.get("PartOfDomain")

    processors = as_list(ps_json(
        "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,"
        "NumberOfLogicalProcessors,MaxClockSpeed | ConvertTo-Json -Compress"))
    memory = as_list(ps_json(
        "Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,Manufacturer,"
        "DeviceLocator,SerialNumber | ConvertTo-Json -Compress"))
    disks = as_list(ps_json(
        "Get-CimInstance Win32_DiskDrive | Select-Object Model,SerialNumber,Size,MediaType,"
        "InterfaceType | ConvertTo-Json -Compress"))
    gpus = as_list(ps_json(
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion "
        "| ConvertTo-Json -Compress"))
    monitors = as_list(ps_json(
        "Get-CimInstance Win32_DesktopMonitor | Select-Object Name,ScreenWidth,ScreenHeight "
        "| ConvertTo-Json -Compress"))

    hardware = {
        "serial": clean(product.get("IdentifyingNumber")),
        "vendor": clean(cs.get("Manufacturer")) or clean(product.get("Vendor")),
        "model": clean(product.get("Name")) or clean(cs.get("Model")),
        "chassis_type": clean((ps_json("Get-CimInstance Win32_SystemEnclosure | "
                                      "Select-Object ChassisTypes | ConvertTo-Json -Compress") or {}
                               ).get("ChassisTypes")),
        "bios_version": clean(bios.get("SMBIOSBIOSVersion")),
        "bios_date": clean(bios.get("ReleaseDate")),
        "cpu": [{"name": clean(p.get("Name")), "cores": p.get("NumberOfCores"),
                 "threads": p.get("NumberOfLogicalProcessors"),
                 "max_clock_mhz": p.get("MaxClockSpeed")} for p in processors],
        "memory": [{"capacity_mb": int(m.get("Capacity", 0) or 0) // (1024 * 1024),
                    "speed_mhz": m.get("Speed"), "manufacturer": clean(m.get("Manufacturer")),
                    "slot": clean(m.get("DeviceLocator")), "serial": clean(m.get("SerialNumber"))}
                   for m in memory],
        "disks": [{"model": clean(d.get("Model")), "serial": clean(d.get("SerialNumber")),
                   "size_gb": round((d.get("Size") or 0) / (1024 ** 3), 1),
                   "media": "SSD" if "ssd" in str(d.get("MediaType", "")).lower() else
                            ("HDD" if d.get("MediaType") else None)} for d in disks],
        "gpu": [{"name": clean(g.get("Name")), "driver_version": clean(g.get("DriverVersion"))}
                for g in gpus],
        "monitors": [{"name": clean(m.get("Name")),
                      "resolution": f"{m.get('ScreenWidth')}x{m.get('ScreenHeight')}"
                      if m.get("ScreenWidth") else None,
                      "manufacturer": None, "serial": None} for m in monitors],
    }

    boot = os_row.get("LastBootUpTime")
    uptime = None
    if isinstance(boot, str):
        try:
            stamp = boot.split(".")[0]
            delta = datetime.now() - datetime.fromisoformat(stamp)
            uptime = int(delta.total_seconds())
        except ValueError:
            uptime = None

    os_info = {
        "family": "windows",
        "caption": clean(os_row.get("Caption")) or f"Windows {platform.release()}",
        "version": clean(os_row.get("Version")),
        "build": clean(str(os_row.get("BuildNumber") or "")),
        "install_date": clean(str(os_row.get("InstallDate") or "")),
        "locale": clean(os_row.get("Locale")),
        "timezone": time.tzname[0] if time.tzname else None,
        "uptime_s": uptime,
        "arch": clean(os_row.get("OSArchitecture")) or platform.machine(),
    }

    network = collect_windows_network()
    software = collect_windows_software()
    users = collect_windows_users()
    security = collect_windows_security()

    return {"schema_version": SCHEMA_VERSION, "agent_version": AGENT_VERSION,
            "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "identity": identity, "hardware": hardware, "os": os_info, "network": network,
            "software": software, "users": users, "security": security}


def collect_windows_network() -> dict:
    rows = as_list(ps_json(
        "Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | "
        "Select-Object Description,MACAddress,IPAddress,IPSubnet,DefaultIPGateway,DNSServerSearchOrder,DHCPEnabled"
        " | ConvertTo-Json -Compress"))
    interfaces = []
    for row in rows:
        ipv4 = next((ip for ip in as_list(row.get("IPAddress")) if ":" not in str(ip)), None)
        ipv6 = next((ip for ip in as_list(row.get("IPAddress")) if ":" in str(ip)), None)
        interfaces.append({
            "name": clean(row.get("Description")),
            "mac": mac_normalize(row.get("MACAddress")),
            "ipv4": clean(ipv4), "ipv6": clean(ipv6),
            "mask": clean((as_list(row.get("IPSubnet")) or [None])[0]),
            "gateway": clean((as_list(row.get("DefaultIPGateway")) or [None])[0]),
            "dns": [str(x) for x in as_list(row.get("DNSServerSearchOrder"))],
            "dhcp": bool(row.get("DHCPEnabled")),
            "speed_mbps": None,
        })
    return {"interfaces": [i for i in interfaces if i["name"]]}


def collect_windows_software() -> list[dict]:
    script = r"""
$paths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$items = foreach ($p in $paths) {
  Get-ItemProperty $p -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName } |
    Select-Object DisplayName, DisplayVersion, Publisher, InstallDate, UninstallString
}
$items | ConvertTo-Json -Compress
"""
    rows = as_list(ps_json(script))
    seen = set()
    out = []
    for row in rows:
        name = clean(row.get("DisplayName"))
        if not name:
            continue
        version = clean(row.get("DisplayVersion"))
        key = (name.lower(), version or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "version": version, "vendor": clean(row.get("Publisher")),
                    "install_date": clean(row.get("InstallDate")),
                    "uninstall_hint": clean(row.get("UninstallString")), "source": "registry"})
    return out


def collect_windows_users() -> dict:
    primary = None
    try:
        primary = clean(os.environ.get("USERNAME"))
    except Exception:
        pass
    admins = as_list(ps_json(
        "Get-LocalGroupMember -Group Administrators -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"))
    logged = as_list(ps_json(
        "Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty UserName | ConvertTo-Json -Compress"))
    return {"primary": primary,
            "logged_on": [x.split("\\")[-1] for x in logged if x],
            "last_logons": [], "local_admins": [str(a).split("\\")[-1] for a in admins]}


def collect_windows_security() -> dict:
    av = as_list(ps_json(
        "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct "
        "-ErrorAction SilentlyContinue | Select-Object displayName,productState "
        "| ConvertTo-Json -Compress"))
    av_name = clean(av[0].get("displayName")) if av else None
    firewall = as_list(ps_json(
        "Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json -Compress"))
    firewall_on = [str(p.get("Name")).lower() for p in firewall if p.get("Enabled")]
    bitlocker = run(["manage-bde", "-status", "C:"], timeout=30)
    disk = None
    if bitlocker:
        disk = "on" if "Fully Encrypted" in bitlocker else (
            "off" if "Fully Decrypted" in bitlocker else "partial")
    tpm = as_list(ps_json(
        "Get-CimInstance -Namespace root/cimv2/security/microsofttpm -ClassName Win32_Tpm "
        "-ErrorAction SilentlyContinue | Select-Object SpecVersion | ConvertTo-Json -Compress"))
    secure_boot = run(["powershell", "-NoProfile", "-Command",
                       "(Confirm-SecureBootUEFI) -as [string]"], timeout=20)
    pending = as_list(ps_json(
        "Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending' "
        "-ErrorAction SilentlyContinue | ConvertTo-Json -Compress"))
    return {
        "av_product": av_name, "av_up_to_date": None,
        "firewall_profiles_on": firewall_on,
        "disk_encryption": disk,
        "tpm_version": clean(tpm[0].get("SpecVersion")) if tpm else None,
        "secure_boot": (secure_boot.strip().lower() == "true") if secure_boot else None,
        "pending_reboot": bool(pending),
        "last_patch_date": None,
    }


# ----------------------------------------------------------------------- Linux
def read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def collect_linux() -> dict:
    hostname = socket.gethostname()
    machine_id = read_file("/etc/machine-id") or read_file("/var/lib/dbus/machine-id")
    osr = {}
    for line in (read_file("/etc/os-release") or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            osr[key] = value.strip('"')

    cpu_name, cores, threads = None, None, None
    cpuinfo = read_file("/proc/cpuinfo") or ""
    match = re.search(r"model name\s*:\s*(.+)", cpuinfo)
    if match:
        cpu_name = match.group(1).strip()
    cores = cpuinfo.count("cpu cores") or None if cpuinfo else None
    threads = cpuinfo.count("processor\t") or None

    mem_total_kb = None
    for line in (read_file("/proc/meminfo") or "").splitlines():
        if line.startswith("MemTotal:"):
            mem_total_kb = int(re.sub(r"[^0-9]", "", line.split(":")[1]))
            break

    disks = []
    try:
        for entry in sorted(Path("/sys/block").iterdir()):
            name = entry.name
            if name.startswith(("loop", "ram", "dm-", "sr")):
                continue
            size = read_file(f"/sys/block/{name}/size")
            model = read_file(f"/sys/block/{name}/device/model")
            serial = read_file(f"/sys/block/{name}/device/serial")
            if not size:
                continue
            rotational = read_file(f"/sys/block/{name}/queue/rotational")
            disks.append({"model": clean(model) or name, "serial": clean(serial),
                          "size_gb": round(int(size) * 512 / (1024 ** 3), 1),
                          "media": "SSD" if rotational == "0" else ("HDD" if rotational else None)})
    except OSError:
        pass

    dmidecode = run(["dmidecode", "-s", "system-serial-number"]) if os.geteuid() == 0 else None
    vendor = run(["dmidecode", "-s", "system-manufacturer"]) if os.geteuid() == 0 else None
    model = run(["dmidecode", "-s", "system-product-name"]) if os.geteuid() == 0 else None
    bios = run(["dmidecode", "-s", "bios-version"]) if os.geteuid() == 0 else None

    uptime_s = None
    raw_uptime = read_file("/proc/uptime")
    if raw_uptime:
        uptime_s = int(float(raw_uptime.split()[0]))

    interfaces = collect_linux_network()
    software = collect_linux_software()

    users = {"primary": clean(os.environ.get("USER") or os.environ.get("LOGNAME")),
             "logged_on": [], "last_logons": [], "local_admins": []}
    who = run(["who"])
    if who:
        users["logged_on"] = sorted({line.split()[0] for line in who.splitlines() if line.strip()})

    return {
        "schema_version": SCHEMA_VERSION, "agent_version": AGENT_VERSION,
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "identity": {"machine_id": clean(machine_id), "hostname": hostname,
                     "domain": None, "domain_joined": None},
        "hardware": {
            "serial": clean(dmidecode), "vendor": clean(vendor), "model": clean(model),
            "chassis_type": None, "bios_version": clean(bios), "bios_date": None,
            "cpu": [{"name": cpu_name, "cores": cores, "threads": threads,
                     "max_clock_mhz": None}],
            "memory": [{"capacity_mb": mem_total_kb // 1024 if mem_total_kb else None,
                        "speed_mhz": None, "manufacturer": None, "slot": None, "serial": None}],
            "disks": disks, "gpu": [], "monitors": [],
        },
        "os": {"family": "linux", "caption": osr.get("PRETTY_NAME") or platform.platform(),
               "version": osr.get("VERSION_ID"), "build": platform.release(),
               "install_date": None, "locale": os.environ.get("LANG"),
               "timezone": read_file("/etc/timezone"), "uptime_s": uptime_s,
               "arch": platform.machine()},
        "network": {"interfaces": interfaces},
        "software": software,
        "users": users,
        "security": {"av_product": None, "av_up_to_date": None, "firewall_profiles_on": [],
                     "disk_encryption": None, "tpm_version": None, "secure_boot": None,
                     "pending_reboot": None, "last_patch_date": None},
    }


def collect_linux_network() -> list[dict]:
    interfaces = []
    raw = run(["ip", "-j", "addr"])
    route_raw = run(["ip", "-j", "route"])
    gateways: dict[str, str] = {}
    if route_raw:
        try:
            for row in json.loads(route_raw):
                if row.get("gateway") and row.get("dev"):
                    gateways[row["dev"]] = row["gateway"]
        except json.JSONDecodeError:
            pass
    if raw:
        try:
            for item in json.loads(raw):
                name = item.get("ifname")
                addrs = item.get("addr_info") or []
                ipv4 = next((a.get("local") for a in addrs if a.get("family") == "inet"), None)
                ipv6 = next((a.get("local") for a in addrs if a.get("family") == "inet6"), None)
                mask = next((a.get("prefixlen") for a in addrs if a.get("family") == "inet"), None)
                dns = []
                resolv = read_file("/etc/resolv.conf") or ""
                dns = re.findall(r"nameserver\s+(\S+)", resolv)[:3]
                interfaces.append({
                    "name": name, "mac": mac_normalize(read_file(f"/sys/class/net/{name}/address")),
                    "ipv4": ipv4, "ipv6": ipv6,
                    "mask": f"{mask}" if mask is not None else None,
                    "gateway": gateways.get(name), "dns": dns, "dhcp": None,
                    "speed_mbps": None,
                })
        except (json.JSONDecodeError, TypeError):
            pass
    return [i for i in interfaces if i.get("name")]


def collect_linux_software() -> list[dict]:
    items: list[dict] = []
    if Path("/usr/bin/dpkg-query").exists() or Path("/bin/dpkg-query").exists():
        out = run(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${Maintainer}\\n"], timeout=60)
        if out:
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    items.append({"name": parts[0], "version": parts[1],
                                  "vendor": parts[2] if len(parts) > 2 else None,
                                  "install_date": None, "uninstall_hint": None, "source": "dpkg"})
            return items
    if run(["rpm", "-qa", "--qf", "%{NAME}\\t%{VERSION}\\n"], timeout=60):
        out = run(["rpm", "-qa", "--qf", "%{NAME}\\t%{VERSION}\\n"])
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                items.append({"name": parts[0], "version": parts[1], "vendor": None,
                              "install_date": None, "uninstall_hint": None, "source": "rpm"})
    return items


# ------------------------------------------------------------------------- push
def normalize_server(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    if not re.search(r":\d+(/|$)", value.split("://", 1)[1]):
        value += ":8091"
    return value


def http_json(url: str, payload: bytes, headers: dict, timeout: int = 30):
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    req = Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (LAN by-IP, HMAC)
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (URLError, TimeoutError, OSError) as exc:
        return None, str(exc)


def do_enroll(args) -> int:
    cfg = load_config()
    server = normalize_server(args.server)
    machine_id = None
    hostname = socket.gethostname()
    if IS_WINDOWS:
        try:
            import winreg  # noqa: PLC0415
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | 0x0100) as key:
                machine_id = clean(winreg.QueryValueEx(key, "MachineGuid")[0])
        except Exception:
            pass
    else:
        machine_id = read_file("/etc/machine-id")

    body = json.dumps({"token": args.enroll, "machine_id": machine_id, "hostname": hostname,
                       "agent_version": AGENT_VERSION}).encode()
    status, text = http_json(server + "/api/v1/enroll", body,
                             {"Content-Type": "application/json"})
    if status != 200:
        print(f"enroll gagal ({status}): {text}", file=sys.stderr)
        return 1
    data = json.loads(text)
    cfg.update({"server": server, "agent_id": data["agent_id"],
                "agent_secret": data["agent_secret"],
                "interval_s": data.get("next_interval_s", 3600)})
    save_config(cfg)
    print(f"enrolled: agent_id={data['agent_id']} server={server} config={CONFIG_PATH}")
    return 0


def sign_headers(secret: str, raw: bytes, ts: str | None = None, nonce: str | None = None) -> dict:
    ts = ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nonce = nonce or uuid.uuid4().hex
    signature = hmac.new(secret.encode(), ts.encode() + nonce.encode() + raw,
                         hashlib.sha256).hexdigest()
    return {"X-Rani-Digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "X-Rani-Signature": signature, "X-Rani-Timestamp": ts, "X-Rani-Nonce": nonce}


def push_payload(payload: dict, cfg: dict, server: str | None = None) -> int:
    agent_id = cfg.get("agent_id")
    secret = cfg.get("agent_secret")
    base = normalize_server(server or cfg.get("server") or "")
    if not agent_id or not secret:
        print("belum enroll: jalankan `raniPush --enroll <token> <server>`", file=sys.stderr)
        return 1
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "X-Rani-Agent-Id": agent_id}
    headers.update(sign_headers(secret, raw))
    status, text = http_json(base + "/api/v1/ingest/push", raw, headers)
    if status in (200, 202):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        if data.get("next_interval_s"):
            cfg["interval_s"] = data["next_interval_s"]
            save_config(cfg)
        duplicate = " (idempotent)" if data.get("duplicate") else ""
        print(f"push ok{duplicate}: report={data.get('report_id')} asset={data.get('asset_id')} "
              f"next={data.get('next_interval_s')}s")
        return 0
    print(f"push gagal ({status}): {text}", file=sys.stderr)
    return 2


def spool_payload(payload: dict) -> Path:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SPOOL_DIR / f"payload-{stamp}-{uuid.uuid4().hex[:6]}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def flush_spool(cfg: dict) -> None:
    if not SPOOL_DIR.exists():
        return
    for path in sorted(SPOOL_DIR.glob("payload-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if push_payload(payload, cfg) == 0:
            path.unlink(missing_ok=True)
            print(f"spool terkirim: {path.name}")
        else:
            break  # server masih tidak terjangkau; sisakan untuk run berikutnya


def prune_spool(max_age_days: int = 7) -> None:
    if not SPOOL_DIR.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for path in SPOOL_DIR.glob("payload-*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="raniPush", description="RANI inventory agent")
    parser.add_argument("server", nargs="?", help="server RANI, mis. 192.168.88.92:8091")
    parser.add_argument("--enroll", metavar="TOKEN", help="enroll agent dengan token")
    parser.add_argument("--collect", action="store_true", help="cetak payload JSON lalu keluar")
    parser.add_argument("--from-file", metavar="PATH", help="kirim payload dari file JSON")
    args = parser.parse_args(argv)

    if args.collect:
        payload = collect_windows() if IS_WINDOWS else collect_linux()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.enroll:
        if not args.server:
            print("butuh server: raniPush --enroll <token> <server>", file=sys.stderr)
            return 1
        return do_enroll(args)

    cfg = load_config()
    if args.from_file:
        try:
            payload = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"gagal baca payload: {exc}", file=sys.stderr)
            return 1
    else:
        payload = collect_windows() if IS_WINDOWS else collect_linux()

    prune_spool()
    flush_spool(cfg)
    status = push_payload(payload, cfg, args.server)
    if status == 2:  # server tidak terjangkau / error sementara → spool
        path = spool_payload(payload)
        print(f"terspool untuk run berikutnya: {path}")
        return 0
    if status != 0:
        return 1
    flush_spool(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())