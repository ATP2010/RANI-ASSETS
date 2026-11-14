"""Unduhan artefak agent dari browser (/agents).

File tidak dibundel di image: compose me-mount `release/` dan `scripts/` read-only
ke path yang dikonfigurasi RANI_AGENT_DIR / RANI_AGENT_SCRIPTS_DIR. Nama file
dibatasi allowlist — tidak ada path dari user yang menyentuh filesystem.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.deps import require_user
from app.models import AppUser

router = APIRouter(include_in_schema=False, tags=["downloads"])
settings = get_settings()

# name → (label, sumber direktori)
ARTIFACTS: dict[str, tuple[str, str]] = {
    "raniPush-signed.exe": ("raniPush.exe bertanda tangan", "release"),
    "raniPush.exe": ("raniPush.exe tanpa signature", "release"),
    "raniPush-portable.zip": ("Paket portable (python embeddable)", "release"),
    "rani-push-signing.cer": ("Sertifikat publik RANI Internal Code Signing", "release"),
    "install-cert.ps1": ("Script pemasangan sertifikat (PowerShell)", "scripts"),
}

_MEDIA_TYPES = {
    ".exe": "application/vnd.microsoft.portable-executable",
    ".zip": "application/zip",
    ".cer": "application/pkix-cert",
    ".ps1": "text/plain; charset=utf-8",
}


def _base_dir(kind: str) -> Path:
    return Path(settings.RANI_AGENT_DIR if kind == "release" else settings.RANI_AGENT_SCRIPTS_DIR)


def artifact_rows() -> list[dict]:
    """Metadata untuk halaman /agents (tanpa membaca isi file)."""
    rows = []
    for name, (label, kind) in ARTIFACTS.items():
        path = _base_dir(kind) / name
        size = path.stat().st_size if path.is_file() else None
        rows.append({"name": name, "label": label, "size": size,
                     "size_mb": round(size / 1048576, 2) if size else None,
                     "available": size is not None})
    return rows


@router.get("/downloads/{name}")
async def download(name: str, user: AppUser = Depends(require_user("reader"))):
    entry = ARTIFACTS.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="artefak tidak dikenal")
    path = _base_dir(entry[1]) / name
    if not path.is_file():
        raise HTTPException(status_code=404,
                            detail=f"{name} belum tersedia di server — jalankan "
                                   "scripts/build-exe.sh / sign-exe.sh / build-portable.sh")
    media = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=name)