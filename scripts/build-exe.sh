#!/usr/bin/env bash
# Build raniPush.exe dari Linux memakai Wine + Python Windows (embeddable) + PyInstaller.
#
# Prasyarat (sekali, butuh root):
#   apt-get install -y --no-install-recommends wine64 unzip curl
#
# Catatan Ubuntu 24.04: paket `wine64` hanya menyediakan /usr/lib/wine/wine64
# (tidak ada wrapper `wine64` di PATH) — script ini mendeteksinya otomatis.
#
# Pakai:  bash scripts/build-exe.sh
# Hasil:  release/raniPush.exe (single file, console)
set -euo pipefail

cd "$(dirname "$0")/.."

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-rani}"
export WINEARCH="${WINEARCH:-win64}"
export WINEDEBUG="${WINEDEBUG:--all}"

# --- cari binary wine ------------------------------------------------------------
WINE_BIN="${WINE_BIN:-}"
if [[ -z "${WINE_BIN}" ]]; then
  for candidate in wine64 wine /usr/lib/wine/wine64; do
    if command -v "${candidate}" >/dev/null 2>&1; then WINE_BIN="${candidate}"; break; fi
  done
fi
if [[ -z "${WINE_BIN}" || ! -x "$(command -v "${WINE_BIN}" 2>/dev/null || echo /nonexistent)" ]]; then
  echo "ERROR: wine tidak ditemukan. Install: apt-get install -y --no-install-recommends wine64" >&2
  exit 1
fi
echo "wine     : ${WINE_BIN} ($("${WINE_BIN}" --version 2>/dev/null || echo '?'))"

PY_DIR="${WINEPREFIX}/drive_c/Python313"
WIN_PY="${PY_DIR}/python.exe"
PY_EMBED_URL="${PY_EMBED_URL:-https://www.python.org/ftp/python/3.13.1/python-3.13.1-embed-amd64.zip}"
CACHE_DIR="${CACHE_DIR:-/var/cache/rani-build}"
mkdir -p "${CACHE_DIR}"

# --- siapkan Python Windows (embeddable, tanpa installer MSI) ---------------------
if [[ ! -x "${WIN_PY}" ]]; then
  echo "== siapkan Python 3.13 embeddable di ${PY_DIR} =="
  mkdir -p "${PY_DIR}" "${CACHE_DIR}"
  [[ -f "${CACHE_DIR}/python-embed.zip" ]] || \
    curl -fsSL -o "${CACHE_DIR}/python-embed.zip" "${PY_EMBED_URL}"
  [[ -f "${CACHE_DIR}/get-pip.py" ]] || \
    curl -fsSL -o "${CACHE_DIR}/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  unzip -oq "${CACHE_DIR}/python-embed.zip" -d "${PY_DIR}"

  # aktifkan site-packages supaya pip/pyinstaller bisa dipakai
  "${WINE_BIN}" cmd /c exit 0 >/dev/null 2>&1 || true
  python3 - "${PY_DIR}" <<'PYEOF'
import pathlib, sys
base = pathlib.Path(sys.argv[1])
pth = base / "python313._pth"
text = pth.read_text().replace("#import site", "import site")
if "Lib\\site-packages" not in text:
    text += "\nLib\\site-packages\n"
pth.write_text(text)
PYEOF

  "${WINE_BIN}" "${WIN_PY}" "${CACHE_DIR}/get-pip.py" --no-warn-script-location | tail -2
fi

echo "== pastikan PyInstaller =="
"${WINE_BIN}" "${WIN_PY}" -m pip install --no-warn-script-location -q "pyinstaller==6.11.1"

mkdir -p release
rm -f release/raniPush.exe

echo "== build exe =="
"${WINE_BIN}" "${WIN_PY}" -m PyInstaller --noconfirm --clean \
  --distpath release --workpath build/pyinstaller agent/raniPush.spec | tail -3

ls -lh release/raniPush.exe
file release/raniPush.exe || true

echo
echo "== smoke test --collect (Wine butuh pseudo-tty; kalau gagal, tes di Windows) =="
if command -v script >/dev/null 2>&1; then
  script -qec "${WINE_BIN} release/raniPush.exe --collect" /tmp/rani-exe-smoke.out >/dev/null 2>&1 || true
  /tmp/wsenv/bin/python - <<'PY' 2>/dev/null || head -c 300 /tmp/rani-exe-smoke.out
import json, pathlib
raw = pathlib.Path('/tmp/rani-exe-smoke.out').read_text().replace('\r', '')
payload = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
print('payload valid JSON | schema_version=', payload['schema_version'],
      '| os=', payload['os']['caption'])
PY
else
  echo "lewati smoke test (butuh util 'script')"
fi

echo
echo "Selesai: $(pwd)/release/raniPush.exe"