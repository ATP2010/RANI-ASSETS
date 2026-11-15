#!/usr/bin/env bash
# Pack ekstensi RANI Actions -> release/rani-actions-extension.zip (untuk "Load unpacked").
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE=/tmp/rani-actions-extension
rm -rf "${STAGE}"
mkdir -p "${STAGE}/rani-actions-extension"
for f in manifest.json content.js background.js popup.html popup.js icon-48.png icon-128.png install-extension.ps1 uninstall-extension.ps1; do
    cp "${ROOT}/extension/${f}" "${STAGE}/rani-actions-extension/${f}"
done
ls release/ >/dev/null 2>&1 || mkdir -p release
rm -f "${ROOT}/release/rani-actions-extension.zip"
(cd "${STAGE}" && zip -qr "${ROOT}/release/rani-actions-extension.zip" rani-actions-extension)
echo "== isi zip =="
unzip -l "${ROOT}/release/rani-actions-extension.zip"
echo "== sha256 =="
sha256sum "${ROOT}/release/rani-actions-extension.zip"
