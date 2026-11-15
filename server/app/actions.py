"""Actions asset gaya Lansweeper ("Create and run actions" / Configuration > Asset Pages).

Action disimpan di tabel `asset_actions` dan dikelola lewat menu **Setup → Actions**
(hanya pemegang `setup.manage`). Setiap action adalah:

- `kind='link'` — hyperlink dengan parameter `{placeholders}` (dieksekusi di mesin
  klien: browser membuka URL/protokol handler), atau
- `kind='copy'` — teks yang disalin ke clipboard klien (mis. `mstsc /v:…`).

Parameter (sama dengan Lansweeper): {ipaddress} {assetname} {hostname} {dnsname}
{fqdn} {domain} {mac} {tag} {assetid}. Dieksekusi klien — server tidak pernah
membuka koneksi ke target dan tidak menyimpan credential.
"""
import hashlib
import hmac
import re
import time
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AssetAction

settings = get_settings()

ALLOWED_PLACEHOLDERS = ("ipaddress", "assetname", "hostname", "dnsname", "fqdn",
                        "domain", "mac", "tag", "assetid", "actionpath")
ALLOWED_LINK_SCHEMES = ("http", "https", "ftp", "file", "rdp", "ssh", "telnet",
                        "vnc", "winbox", "mqtt", "ldap", "ldaps")
ALLOWED_SCRIPT_EXT = (".bat", ".cmd", ".ps1", ".exe", ".msi")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Snapshot default — juga dipakai migration 0007 untuk seed awal (jangan diubah sembarangan).
DEFAULT_ACTIONS: list[tuple[str, str, str, bool, bool, int]] = [
    ("Buka di browser (HTTP)",  "http://{ipaddress}",      "link", False, False, 10),
    ("Buka di browser (HTTPS)", "https://{ipaddress}",     "link", False, False, 20),
    ("Buka berbagi file (C$)",  "file:///{ipaddress}/c$",  "link", False, True,  30),
    ("Remote Desktop (RDP)",    "rdp://{ipaddress}",       "link", False, True,  40),
    ("SSH",                     "ssh://{ipaddress}",       "link", False, True,  50),
    ("VNC",                     "vnc://{ipaddress}",       "link", False, True,  60),
    ("Salin `mstsc` untuk RDP", "mstsc /v:{ipaddress}",    "copy", False, False, 70),
    ("Salin alamat IP",         "{ipaddress}",             "copy", False, False, 80),
    ("Salin MAC",               "{mac}",                   "copy", False, False, 90),
    ("Salin hostname",          "{hostname}",              "copy", False, False, 100),
]


def validate_action(name: str, command: str, kind: str) -> str | None:
    """Return pesan error (Indonesia) atau None bila valid."""
    if not (name or "").strip():
        return "nama action wajib diisi"
    if len(name.strip()) > 96:
        return "nama maksimal 96 karakter"
    command = (command or "").strip()
    if not command:
        return "perintah/URL/nama file wajib diisi"
    if len(command) > 512:
        return "perintah maksimal 512 karakter"
    unknown = sorted({m.group(1) for m in _PLACEHOLDER_RE.finditer(command)}
                     - set(ALLOWED_PLACEHOLDERS))
    if unknown:
        return ("placeholder tidak dikenal: " + ", ".join("{%s}" % p for p in unknown)
                + " (diizinkan: " + " ".join("{%s}" % p for p in ALLOWED_PLACEHOLDERS) + ")")
    if kind == "link":
        m = _SCHEME_RE.match(command)
        if not m:
            return ("action link harus berupa URL berskema "
                    "(http:, https:, rdp:, ssh:, file:, …)")
        scheme = m.group(1).lower()
        if scheme not in ALLOWED_LINK_SCHEMES:
            return f"skema '{scheme}:' tidak diizinkan (diizinkan: {', '.join(ALLOWED_LINK_SCHEMES)})"
    elif kind == "copy":
        return None
    elif kind == "script":
        parts = command.split(None, 1)
        fname = parts[0]
        if not _FILENAME_RE.match(fname):
            return f"nama file tidak valid: '{fname}' (tanpa path, hanya huruf/angka/._-)"
        ext = "." + fname.rpartition(".")[2].lower() if "." in fname else ""
        if ext not in ALLOWED_SCRIPT_EXT:
            return f"ekstensi '{ext or '(tidak ada)'}' tidak diizinkan ({', '.join(ALLOWED_SCRIPT_EXT)})"
        target = _actions_dir() / fname
        if not target.is_file():
            return f"file tidak ditemukan di folder actions server: {fname}"
        # sisanya dianggap args — placeholder sudah divalidasi di atas
        return None
    else:
        return "kind harus 'link', 'copy', atau 'script'"
    return None


def _actions_dir() -> Path:
    return Path(settings.RANI_ACTIONS_DIR)


def action_file_token(filename: str, ttl: int, pepper: str) -> tuple[int, str]:
    exp = int(time.time()) + int(ttl)
    sig = hmac.new(pepper.encode(), f"actionfile:{filename}:{exp}".encode(),
                   hashlib.sha256).hexdigest()
    return exp, sig


def verify_action_file_token(filename: str, exp, sig: str) -> bool:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i <= 0 or not sig:
        return False
    if exp_i < int(time.time()):
        return False
    expected = hmac.new(settings.RANI_INGEST_PEPPER.encode(),
                        f"actionfile:{filename}:{exp_i}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _fqdn(asset) -> str:
    host = (getattr(asset, "hostname", "") or "").strip()
    if "." in host:
        return host
    domain = (getattr(asset, "domain", "") or "").strip().lower()
    if host and domain and domain not in ("workgroup", "localhost"):
        return f"{host}.{domain}"
    return host


def asset_params(asset, base_url: str | None = None) -> dict:
    base = (base_url or "").rstrip("/")
    return {
        "ipaddress": (getattr(asset, "ip_last", "") or "").strip(),
        "assetname": (getattr(asset, "hostname", "") or "").strip(),
        "hostname": (getattr(asset, "hostname", "") or "").strip(),
        "fqdn": _fqdn(asset),
        "dnsname": _fqdn(asset),
        "domain": (getattr(asset, "domain", "") or "").strip(),
        "mac": (getattr(asset, "primary_mac", "") or "").strip(),
        "tag": (getattr(asset, "serial", "") or "").strip(),
        "assetid": str(getattr(asset, "id", "") or ""),
        "actionpath": f"{base}/actions/files/" if base else "",
    }


def render_actions(action_rows, asset, base_url: str | None = None) -> list[dict]:
    """Substitusi placeholder untuk satu asset. Action butuh {ipaddress} disembunyikan
    bila asset tak punya IP. kind=script di-render sebagai raniaction://run?..."""
    params = asset_params(asset, base_url)
    items: list[dict] = []
    for row in action_rows:
        command = (row.command or "").strip()
        if not command:
            continue
        if "{ipaddress}" in command and not params["ipaddress"]:
            continue
        item = {"key": str(row.id), "label": row.name, "confirm": bool(row.confirm),
                "advanced": bool(row.advanced), "sort_order": row.sort_order,
                "kind": row.kind}
        if row.kind == "script":
            parts = command.split(None, 1)
            fname = parts[0]
            args = _PLACEHOLDER_RE.sub(lambda m: params.get(m.group(1), ""),
                                       parts[1] if len(parts) > 1 else "").strip()
            exp, sig = action_file_token(fname, settings.RANI_ACTIONS_URLTTL_S,
                                         settings.RANI_INGEST_PEPPER)
            item["href"] = (f"raniaction://run?f={quote(fname)}"
                            f"&exp={exp}&sig={sig}&a={quote(args)}")
            item["script"] = fname
        else:
            text = _PLACEHOLDER_RE.sub(lambda m: params.get(m.group(1), ""),
                                       command).strip()
            if not text:
                continue
            if row.kind == "link":
                item["href"] = text
            else:
                item["copy"] = text
        items.append(item)
    return items


async def load_action_rows(session: AsyncSession):
    return list((await session.execute(
        select(AssetAction).where(AssetAction.enabled.is_(True))
        .order_by(AssetAction.advanced.asc(), AssetAction.sort_order.asc(),
                  AssetAction.name.asc()))).scalars().all())


def asset_actions(action_rows, asset, base_url: str | None = None) -> list[dict]:
    return render_actions(action_rows, asset, base_url)
