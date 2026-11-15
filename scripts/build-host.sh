#!/usr/bin/env bash
# Build rani-action-host.exe (native messaging host) dari Linux via Wine + embeddable Python.
# Asumsi: prefix Wine sudah ada (jalankan scripts/build-exe.sh sekali bila belum).
# Hasil: release/rani-action-host.exe
set -euo pipefail
cd "$(dirname "$0")/.."

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-rani}"
export WINEARCH="${WINEARCH:-win64}"
export WINEDEBUG="${WINEDEBUG:--all}"

WINE_BIN="${WINE_BIN:-}"
if [[ -z "${WINE_BIN}" ]]; then
  for candidate in wine64 wine /usr/lib/wine/wine64; do
    command -v "${candidate}" >/dev/null && WINE_BIN="${candidate}" && break
  done
fi
PY_DIR="${WINEPREFIX}/drive_c/Python313"
WIN_PY="${PY_DIR}/python.exe"
[[ -f "${WIN_PY}" ]] || { echo "ERROR: prefix Wine belum ada — jalankan scripts/build-exe.sh sekali"; exit 1; }

"${WINE_BIN}" "${WIN_PY}" -m pip install --no-warn-script-location -q "pyinstaller==6.11.1"

mkdir -p release
rm -f release/rani-action-host.exe
"${WINE_BIN}" "${WIN_PY}" -m PyInstaller --noconfirm --clean \
  --distpath release --workpath build/pyinstaller-host \
  --onefile --console --name rani-action-host \
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc \
  agent/rani_action_host.py | tail -2

ls -lh release/rani-action-host.exe

# --- tanda tangani (self-signed) supaya download tidak diblokir SmartScreen ---
if command -v osslsigncode >/dev/null 2>&1 && [[ -f .signing/rani-codesign.pem && -f .signing/rani-codesign.key ]]; then
  OUT=release/rani-action-host-signed.exe
  rm -f "$OUT"
  if osslsigncode sign -certs .signing/rani-codesign.pem -key .signing/rani-codesign.key \
       -n "RANI Actions native host" -h sha256 \
       -in release/rani-action-host.exe -out "$OUT" >/dev/null 2>&1; then
    chmod +x "$OUT"
    echo "signed  : $OUT"
  else
    echo "WARN: signing rani-action-host gagal (lanjut tanpa signature)"
  fi
else
  echo "INFO: osslsigncode / sertifikat tidak ada — host tidak ditandatangani"
fi
