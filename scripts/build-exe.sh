#!/usr/bin/env bash
# Build raniPush.exe dari Linux memakai Wine + Python Windows (PyInstaller).
#
# Prasyarat (sekali):
#   apt-get install -y --no-install-recommends wine64
#   curl -LO https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe
#   WINEPREFIX=$HOME/.wine-rani WINEDEBUG=-all wine64 python-3.13.1-amd64.exe \
#       /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1
#
# Pakai:  bash scripts/build-exe.sh
# Hasil:  release/raniPush.exe  (single file, console)
set -euo pipefail

cd "$(dirname "$0")/.."

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-rani}"
export WINEDEBUG="${WINEDEBUG:--all}"
WINE_BIN="${WINE_BIN:-wine64}"
PY_URL="${PY_URL:-https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe}"
PY_LOCAL="${PY_LOCAL:-/opt/cache/python-3.13.1-amd64.exe}"

command -v "${WINE_BIN}" >/dev/null || {
  echo "ERROR: ${WINE_BIN} tidak ada. Install dulu: apt-get install -y --no-install-recommends wine64" >&2
  exit 1
}

wine_python() { "${WINE_BIN}" "$WINEPREFIX/drive_c/Program Files/Python313/python.exe" "$@"; }

if ! wine_python -V >/dev/null 2>&1; then
  echo "== install Python Windows ke prefix ${WINEPREFIX} =="
  mkdir -p "$(dirname "${PY_LOCAL}")"
  [[ -f "${PY_LOCAL}" ]] || curl -fsSL -o "${PY_LOCAL}" "${PY_URL}"
  "${WINE_BIN}" "${PY_LOCAL}" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1
  sleep 5
fi

echo "== pastikan PyInstaller terpasang =="
wine_python -m pip install --disable-pip-version-check -q "pyinstaller==6.11.1"

mkdir -p release
rm -f release/raniPush.exe

echo "== build exe =="
wine_python -m PyInstaller --noconfirm --clean --distpath release --workpath build/pyinstaller \
  agent/raniPush.spec

ls -lh release/raniPush.exe
file release/raniPush.exe || true

echo
echo "Smoke test di Wine (harus mengeluarkan JSON payload):"
"${WINE_BIN}" release/raniPush.exe --collect | head -c 400 || true
echo
echo "Selesai: $(pwd)/release/raniPush.exe"