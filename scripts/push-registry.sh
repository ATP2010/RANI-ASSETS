#!/usr/bin/env bash
# Build image server RANI dan push ke registry lokal (untuk migrasi server dev/prod).
# Pakai: ./scripts/push-registry.sh [tag]
set -euo pipefail

cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-192.168.88.92:5000}"
TAG="${1:-${TAG:-latest}}"
IMAGE="${RANI_IMAGE:-rani-server:dev}"
TARGET="${REGISTRY}/rani-server:${TAG}"

echo "== build ${IMAGE} =="
docker build -t "${IMAGE}" .

echo "== tag + push ${TARGET} =="
docker tag "${IMAGE}" "${TARGET}"
docker push "${TARGET}"

echo
echo "Di server tujuan:"
echo "  git clone <repo> && cd ProjectDev"
echo "  cp .env.example .env   # isi password + pepper (pepper harus SAMA bila DB dibawa)"
echo "  RANI_IMAGE=${TARGET} docker compose pull"
echo "  RANI_IMAGE=${TARGET} docker compose up -d"
echo
echo "Catatan: image ini dipakai bersama oleh service api dan worker."