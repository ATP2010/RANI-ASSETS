#!/usr/bin/env bash
# Build image aplikasi RANI (API + worker + docs + skrip + artefak agent) dan push
# ke Docker Hub: adhityatp/raniassets:<tag> (+ :latest).
#
# Pakai:
#   bash scripts/push-dockerhub.sh            # tag default 0.1.0 + latest
#   bash scripts/push-dockerhub.sh 0.2.0
#
# Prasyarat: sudah `docker login` sebagai user yang punya akses push ke
# adhityatp/raniassets. Script TIDAK menyimpan kredensial.
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-adhityatp/raniassets}"
TAG="${1:-0.1.0}"
ARTIFACT_DIR="docker/artifacts"

command -v docker >/dev/null || { echo "ERROR: docker tidak ditemukan" >&2; exit 1; }

cleanup() {
  find "${ARTIFACT_DIR}" -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
}
trap cleanup EXIT

# --- artefak agent (exe signed, portable, cert) ------------------------------
echo "== salin artefak agent ke ${ARTIFACT_DIR} =="
mkdir -p "${ARTIFACT_DIR}"
if [[ -f release/raniPush-signed.exe ]]; then
  # hanya file (exe/zip/cer); folder portable/ tidak perlu, zip-nya sudah ada
  find release -maxdepth 1 -type f -exec cp -a {} "${ARTIFACT_DIR}/" \;
  du -sh "${ARTIFACT_DIR}" | awk '{print "   ukuran:", $1}'
else
  echo "   PERINGATAN: release/raniPush-signed.exe tidak ada — image akan tanpa exe."
  echo "   Jalankan dulu: bash scripts/build-exe.sh && bash scripts/sign-exe.sh && bash scripts/build-portable.sh"
fi

# --- build ------------------------------------------------------------------
echo "== build ${IMAGE}:${TAG} =="
RANI_IMAGE="${IMAGE}:${TAG}" docker compose build api

echo "== tag latest =="
if [[ "${TAG}" != "latest" ]]; then
  docker tag "${IMAGE}:${TAG}" "${IMAGE}:latest"
fi

# --- push -------------------------------------------------------------------
echo "== push =="
docker push "${IMAGE}:${TAG}"
[[ "${TAG}" != "latest" ]] && docker push "${IMAGE}:latest"

echo
echo "Selesai:"
echo "  ${IMAGE}:${TAG}"
echo "  ${IMAGE}:latest"
docker image ls "${IMAGE}" --format '  {{.Repository}}:{{.Tag}}  {{.Size}}  {{.ID}}'
echo
echo "Di server dev:"
echo "  docker pull ${IMAGE}:${TAG}"
echo "  RANI_IMAGE=${IMAGE}:${TAG} docker compose -f docker-compose.hub.yml up -d"
echo "Panduan lengkap: docs/deploy-dockerhub.md"