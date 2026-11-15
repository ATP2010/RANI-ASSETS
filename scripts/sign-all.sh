#!/usr/bin/env bash
# Tanda tangani semua artefak .exe RANI (raniPush + rani-action-host) dengan
# sertifikat internal (gratis, self-signed) agar SmartScreen tidak memblokir
# download. Untuk trust otomatis di Windows, beli OV/EV cert (lihat docs).
set -euo pipefail
cd "$(dirname "$0")/.."

CERT=.signing/rani-codesign.pem
KEY=.signing/rani-codesign.key
command -v osslsigncode >/dev/null || { echo "ERROR: osslsigncode tidak ada"; exit 1; }
[[ -f "$CERT" && -f "$KEY" ]] || { echo "ERROR: sertifikat .signing tidak ada. Jalankan scripts/sign-exe.sh sekali."; exit 1; }

sign_one() {
  local in="$1" name="$2"
  [[ -f "$in" ]] || { echo "SKIP (tidak ada): $in"; return; }
  local out="${in%.exe}-signed.exe"
  rm -f "$out"
  if osslsigncode sign -certs "$CERT" -key "$KEY" -n "$name" -h sha256 \
       -in "$in" -out "$out" >/dev/null 2>&1; then
    chmod +x "$out"
    echo "OK   : $in -> $out"
  else
    echo "FAIL : $in"
  fi
}

sign_one release/raniPush.exe "RANI raniPush agent"
sign_one release/rani-action-host.exe "RANI Actions native host"

echo
echo "Verifikasi (harus 'Valid' setelah install .cer di PC target):"
for f in release/raniPush-signed.exe release/rani-action-host-signed.exe; do
  [[ -f "$f" ]] && osslsigncode verify -in "$f" 2>&1 | grep -Ei 'Number of signatures|Verification' | sed "s/^/  $f: /"
done
