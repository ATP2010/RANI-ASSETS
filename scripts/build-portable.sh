#!/usr/bin/env bash
# Paket portable raniPush untuk PC yang memblokir exe (Smart App Control / AV ketat).
#
# Isi paket: Python 3.13 embeddable resmi (python.exe ditandatangani Python Software
# Foundation) + raniPush.py + raniPush.cmd. Tidak ada exe buatan sendiri, jadi tidak
# kena blokir "unsigned application".
#
# Pakai:  bash scripts/build-portable.sh
# Hasil:  release/raniPush-portable/  dan  release/raniPush-portable.zip
set -euo pipefail

cd "$(dirname "$0")/.."

PY_EMBED_URL="${PY_EMBED_URL:-https://www.python.org/ftp/python/3.13.1/python-3.13.1-embed-amd64.zip}"
CACHE_DIR="${CACHE_DIR:-/var/cache/rani-build}"
OUT_DIR="release/raniPush-portable"
ZIP="release/raniPush-portable.zip"

mkdir -p "${CACHE_DIR}" release
[[ -f "${CACHE_DIR}/python-embed.zip" ]] || \
  curl -fsSL -o "${CACHE_DIR}/python-embed.zip" "${PY_EMBED_URL}"

rm -rf "${OUT_DIR}" "${ZIP}"
mkdir -p "${OUT_DIR}/python"

unzip -oq "${CACHE_DIR}/python-embed.zip" -d "${OUT_DIR}/python"
cp agent/raniPush.py "${OUT_DIR}/raniPush.py"

cat > "${OUT_DIR}/raniPush.cmd" <<'CMD'
@echo off
setlocal
rem Wrapper supaya bisa dipanggil dari Task Scheduler maupun Command Prompt.
rem Contoh: raniPush.cmd --enroll <token> 192.168.88.92:8091
rem           raniPush.cmd 192.168.88.92:8091
"%~dp0python\python.exe" "%~dp0raniPush.py" %*
exit /b %ERRORLEVEL%
CMD

python3 - "${OUT_DIR}" <<'PYEOF'
import pathlib, sys
out = pathlib.Path(sys.argv[1])
(out / "README.txt").write_text(
    "RANI raniPush - paket portable\r\n"
    "==============================\r\n\r\n"
    "Dipakai bila raniPush.exe diblokir Smart App Control / antivirus.\r\n"
    "Tidak ada exe buatan sendiri di paket ini: hanya python.exe resmi (ditandatangani\r\n"
    "Python Software Foundation) + skrip raniPush.py.\r\n\r\n"
    "Langkah:\r\n"
    " 1. Extract folder ini (mis. ke C:\\Rani-portable)\r\n"
    " 2. PowerShell as Administrator:\r\n"
    "      .\\raniPush.cmd --enroll <TOKEN> 192.168.88.92:8091\r\n"
    "      .\\raniPush.cmd 192.168.88.92:8091\r\n"
    " 3. Jadwalkan (SYSTEM, tiap 60 menit):\r\n"
    "      schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f ^\r\n"
    "        /tr \"C:\\Rani-portable\\raniPush.cmd 192.168.88.92:8091\"\r\n\r\n"
    "Log: C:\\ProgramData\\Rani\\raniPush.log\r\n"
    "Panduan lengkap: docs/agent-windows.md\r\n",
    encoding="utf-8",
)

# ._pth embeddable: aktifkan site-packages agar tidak mengganggu import apa pun,
# dan pastikan direktori skrip ada di sys.path.
pth = out / "python" / "python313._pth"
text = pth.read_text().replace("#import site", "import site")
if ".." not in text:
    text += "..\n"
pth.write_text(text)
PYEOF

python3 - "${OUT_DIR}" "${ZIP}" <<'PYEOF'
import pathlib, sys, zipfile
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(src.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(src.parent))
print(f"{dst}: {len(zf.namelist())} file")
PYEOF

echo "== isi paket =="
ls -lh "${OUT_DIR}" | head
du -sh "${OUT_DIR}" "${ZIP}"
sha256sum "${ZIP}"