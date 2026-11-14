#!/usr/bin/env bash
# Tanda tangani release/raniPush.exe dengan sertifikat code-signing internal.
#
# Kenapa: SmartScreen/Smart App Control menolak exe tanpa signature. Signature
# self-signed menghilangkan status "unsigned", dan setelah sertifikat publiknya
# dipasang di Trusted Publishers PC target (lihat scripts/install-cert.ps1), Windows
# tidak lagi menampilkan peringatan "Unknown publisher".
#
# Catatan penting: sertifikat self-signed TIDAK memberi reputasi SmartScreen seperti
# sertifikat OV/EV dari CA publik. Untuk PC di luar kendali kita, tetap perlu cert CA.
#
# Pakai:  bash scripts/sign-exe.sh [path-exe]
# Hasil:  release/raniPush-signed.exe + release/rani-push-signing.cer (publik)
set -euo pipefail

cd "$(dirname "$0")/.."

EXE="${1:-release/raniPush.exe}"
SIGN_DIR="${SIGN_DIR:-.signing}"
CERT="${SIGN_DIR}/rani-codesign.pem"
KEY="${SIGN_DIR}/rani-codesign.key"
P12="${SIGN_DIR}/rani-codesign.p12"
PUB="${SIGN_DIR}/rani-push-signing.cer"
OUT="${EXE%.exe}-signed.exe"

command -v osslsigncode >/dev/null || {
  echo "ERROR: osslsigncode tidak ada. Install: apt-get install -y --no-install-recommends osslsigncode" >&2
  exit 1
}
[[ -f "${EXE}" ]] || { echo "ERROR: ${EXE} tidak ditemukan" >&2; exit 1; }

mkdir -p "${SIGN_DIR}"
chmod 700 "${SIGN_DIR}"

if [[ ! -f "${CERT}" || ! -f "${KEY}" ]]; then
  echo "== buat sertifikat code-signing internal (berlaku 3 tahun) =="
  openssl req -x509 -newkey rsa:3072 -nodes \
    -keyout "${KEY}" -out "${CERT}" -days 1095 -sha256 \
    -subj "/C=ID/O=RANI Internal/CN=RANI Internal Code Signing" \
    -addext "keyUsage=critical,digitalSignature" \
    -addext "extendedKeyUsage=critical,codeSigning" \
    -addext "basicConstraints=critical,CA:FALSE" 2>/dev/null
  chmod 600 "${KEY}"
  openssl pkcs12 -export -out "${P12}" -inkey "${KEY}" -in "${CERT}" \
    -name "RANI Internal Code Signing" -passout pass:rani 2>/dev/null
  openssl x509 -in "${CERT}" -outform DER -out "${PUB}"
  echo "sertifikat : ${CERT}"
  echo "public cer : ${PUB}"
fi

echo "== sign ${EXE} =="
# Timestamp opsional: sertifikat self-signed tetap bisa di-timestamp; kalau server
# timestamp tidak terjangkau, ulangi tanpa timestamp.
sign() {
  rm -f "${OUT}"
  osslsigncode sign -certs "${CERT}" -key "${KEY}" \
    -n "RANI raniPush agent" -i "http://192.168.88.92:8091" \
    "$@" -h sha256 -in "${EXE}" -out "${OUT}"
}

if sign -t "http://timestamp.sectigo.com" >/dev/null 2>&1; then
  echo "  ditandatangani + timestamp (sectigo)"
elif sign -t "http://timestamp.digicert.com" >/dev/null 2>&1; then
  echo "  ditandatangani + timestamp (digicert)"
elif sign -t "http://timestamp.acs.microsoft.com" >/dev/null 2>&1; then
  echo "  ditandatangani + timestamp (microsoft)"
else
  echo "  timestamp gagal — sign tanpa timestamp"
  sign
fi

chmod +x "${OUT}"

echo
echo "== verifikasi signature =="
osslsigncode verify -in "${OUT}" 2>&1 | grep -Ei 'number of signatures|signer|issuer|message digest|verification' | head -12 || true

cp -f "${PUB}" release/rani-push-signing.cer
echo "sertifikat publik disalin ke release/rani-push-signing.cer"

echo
openssl x509 -in "${CERT}" -noout -subject -dates
openssl x509 -in "${CERT}" -noout -fingerprint -sha256

cat <<EOF

Selesai: $(pwd)/${OUT}
Sertifikat publik untuk PC target: $(pwd)/${PUB}

Di PC Windows (PowerShell as Administrator):
  .\\install-cert.ps1 -CerPath .\\rani-push-signing.cer
  # lalu jalankan exe yang sudah ditandatangani
EOF