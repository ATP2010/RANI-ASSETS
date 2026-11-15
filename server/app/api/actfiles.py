"""Endpoint download file Actions (gaya Lansweeper lansweeper$).

Tidak butuh session — token HMAC (`exp` + `sig`, dibuat saat halaman dirender)
menjadi satu-satunya kredensial: file hanya bisa diambil bila tahu token yang
valid & belum kedaluwarsa. Filename divalidasi ketat (tanpa path, ekstensi
diizinkan, harus ada di RANI_ACTIONS_DIR).
"""
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.actions import ALLOWED_SCRIPT_EXT, verify_action_file_token
from app.config import get_settings

log = logging.getLogger("rani.actfiles")
router = APIRouter(include_in_schema=False)
settings = get_settings()

_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

MEDIA_TYPES = {
    ".bat": "application/octet-stream",
    ".cmd": "application/octet-stream",
    ".ps1": "application/octet-stream",
    ".exe": "application/octet-stream",
    ".msi": "application/octet-stream",
}


@router.get("/actions/files/{filename}")
async def serve_action_file(filename: str, exp: int | None = Query(None),
                            sig: str | None = Query(None)):
    if not _FILENAME_RE.match(filename or ""):
        raise HTTPException(status_code=400, detail="nama file tidak valid")
    ext = "." + filename.rpartition(".")[2].lower() if "." in filename else ""
    if ext not in ALLOWED_SCRIPT_EXT:
        raise HTTPException(status_code=400, detail="ekstensi tidak diizinkan")
    if not verify_action_file_token(filename, exp, sig or ""):
        raise HTTPException(status_code=403, detail="token tidak valid atau kedaluwarsa")

    base = Path(settings.RANI_ACTIONS_DIR).resolve()
    target = (base / filename).resolve()
    if target.parent != base or not target.is_file():
        raise HTTPException(status_code=404, detail="file tidak ada di server")
    return FileResponse(target, media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
                        filename=filename,
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})
