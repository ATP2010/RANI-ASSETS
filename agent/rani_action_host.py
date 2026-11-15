"""Native messaging host 'com.rani.action_host' untuk RANI Actions extension.

Dibaca dari stdin (format Chrome native messaging: 4-byte little-endian panjang
pesan + JSON UTF-8), memvalidasi permintaan dari extension RANI Actions,
men-download file action dari server RANI (token HMAC), lalu mengeksekusinya di
PC pengguna — pola yang sama dengan Lansweeper Shell Execute.

Keamanan:
- origin wajib sama persis dengan `server_origin` di `%ProgramData%\\rani-action\\config.json`
  (dibuat oleh installer; tidak menerima origin lain);
- nama file polos, ekstensi dibatasi (.bat .cmd .ps1 .exe .msi);
- argumen hanya `[A-Za-z0-9._:-]` per token — tidak ada spasi/semicolon/pipe;
- token HMAC diverifikasi server saat download; host tidak menyimpan pepper.

Format pesan masuk (JSON):
  {"type": "rani-action", "origin": "https://rani:8091", "file": "ping.bat",
   "args": "192.168.1.5", "exp": "1794…", "sig": "…", "label": "Ping (skrip)"}

Atau {"type": "ping"} / {"origin": "ping"} → {"ok": true, "version": …}.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
MAX_MESSAGE = 1024 * 1024          # 1 MB — pesan native messaging wajar < 64 KB
MAX_DOWNLOAD = 64 * 1024 * 1024    # 64 MB
TIMEOUT_S = 20

ALLOWED_EXT = {".bat", ".cmd", ".ps1", ".exe", ".msi"}
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ARG_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


def _config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("ProgramData") or r"C:\ProgramData"
        return Path(base) / "rani-action"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "rani-action"


def _read_config() -> dict:
    path = _config_dir() / "config.json"
    if not path.is_file():
        raise RuntimeError(f"config tidak ditemukan: {path} — jalankan install-extension.ps1 dulu")
    return json.loads(path.read_text(encoding="utf-8"))


def _origin_allowed(origin: str, config: dict) -> bool:
    expected = str(config.get("server_origin", "")).rstrip("/").lower()
    got = str(origin or "").rstrip("/").lower()
    return bool(expected) and got == expected


def _split_args(raw: str) -> list[str]:
    tokens = [t for t in (raw or "").split() if t]
    for tok in tokens:
        if not ARG_RE.match(tok):
            raise RuntimeError(f"argumen tidak diizinkan: '{tok}'")
    return tokens


def _download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": f"rani-action-host/{VERSION}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError("file terlalu besar")
    dest.write_bytes(data)
    return len(data)


def _launch(file: Path, args: list[str]) -> None:
    ext = file.suffix.lower()
    if ext == ".ps1":
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(file), *args]
    elif ext in (".bat", ".cmd"):
        cmd = ["cmd.exe", "/c", str(file), *args]
    elif ext == ".msi":
        cmd = ["msiexec.exe", "/i", str(file), *args]
    else:
        cmd = [str(file), *args]
    subprocess.Popen(cmd)


def _handle(msg: dict) -> dict:
    if msg.get("type") == "ping" or msg.get("origin") == "ping":
        return {"ok": True, "version": VERSION}

    config = _read_config()
    origin = str(msg.get("origin") or "").rstrip("/")
    if not _origin_allowed(origin, config):
        return {"ok": False, "error": f"origin tidak diizinkan ({origin or '-'})"}

    file_name = str(msg.get("file") or "").strip()
    if not FILENAME_RE.match(file_name):
        return {"ok": False, "error": f"nama file tidak valid: {file_name!r}"}
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXT:
        return {"ok": False, "error": f"ekstensi {ext!r} tidak diizinkan"}

    args = _split_args(str(msg.get("args") or ""))
    exp = str(msg.get("exp") or "")
    sig = str(msg.get("sig") or "")
    if not exp.isdigit() or not sig:
        return {"ok": False, "error": "exp/sig tidak valid"}
    now = int(time.time())
    if int(exp) < now:
        return {"ok": False, "error": "token kedaluwarsa — reload halaman, klik lagi"}

    tmp_dir = Path(os.environ.get("TEMP") or ("C:\\Windows\\Temp" if os.name == "nt" else "/tmp")) / "rani-action"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    work_dir = tmp_dir / f"run-{secrets.token_hex(8)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / file_name

    url = f"{origin}/actions/files/{file_name}?exp={exp}&sig={sig}"
    _download(url, dest)
    _launch(dest, args)
    return {"ok": True, "output": f"launched {file_name} {' '.join(args)}".strip()}


def _frame_read(stdin) -> bytes | None:
    header = stdin.read(4)
    if len(header) < 4:
        return None
    length = int.from_bytes(header, "little")
    if length <= 0 or length > MAX_MESSAGE:
        raise RuntimeError("pesan terlalu besar atau kosong")
    return stdin.read(length)


def _frame_write(stdout, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stdout.buffer.write(len(data).to_bytes(4, "little") + data)
    stdout.buffer.flush()


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout
    try:
        raw = _frame_read(stdin)
        if raw is None:
            return 0
        msg = json.loads(raw.decode("utf-8"))
        _frame_write(stdout, _handle(msg))
        return 0
    except Exception as exc:  # noqa: BLE001 — pesan error sampai ke extension
        try:
            _frame_write(stdout, {"ok": False, "error": str(exc)})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
