#!/usr/bin/env bash
# =============================================================================
# Sinkronkan image RANI ke Docker Hub otomatis, dijalankan dari server ini.
# =============================================================================
# Kenapa di server, bukan GitHub Actions:
#   - `docker login` di server hanya menyimpan kredensial di ~/.docker/config.json;
#     GitHub Actions tidak bisa memakainya (runner-nya mesin lain, hanya baca
#     repo secrets DOCKERHUB_USERNAME/DOCKERHUB_TOKEN).
#   - Artefak agent (raniPush-signed.exe, portable zip, cert, action-host) ada di
#     release/ yang gitignored dan ditandatangani di server ini. Runner GitHub
#     tidak punya private key penandatangan, jadi image hasil CI tanpa artefak.
#
# Cara kerja:
#   1. Ambil VERSION dari server/app/version.py di origin/main.
#   2. Cek Docker Hub: tag itu sudah ada? -> selesai (tidak build ulang).
#   3. Belum ada: pastikan working tree bersih, fast-forward ke origin/main,
#      lalu build + push lewat scripts/push-dockerhub.sh <VERSION>.
#
# Pemakaian:
#   scripts/sync-dockerhub.sh              # normal (dipakai systemd timer)
#   DRY_RUN=1 scripts/sync-dockerhub.sh    # hanya laporkan, tanpa build/push
#   scripts/sync-dockerhub.sh --force      # build & push walau tag sudah ada
#
# Exit code: 0 = sinkron/tidak perlu apa-apa, 1 = error, 2 = dilewati (tree kotor).
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

IMAGE="${IMAGE:-adhityatp/raniassets}"
NAMESPACE="${IMAGE%%/*}"
NAME="${IMAGE##*/}"
DRY_RUN="${DRY_RUN:-0}"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker tidak ditemukan"
command -v curl   >/dev/null || die "curl tidak ditemukan"

# --- 1. versi terbaru di origin/main -----------------------------------------
log "fetch origin/main"
git fetch --quiet origin main || die "git fetch gagal"

VERSION="$(git show origin/main:server/app/version.py \
  | sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p')"
[[ -n "$VERSION" ]] || die "tidak bisa membaca VERSION dari origin/main"
log "versi di origin/main: $VERSION"

# --- 2. sudah ada di Docker Hub? ---------------------------------------------
hub_has_tag() {
  curl -fsS --max-time 20 \
    "https://hub.docker.com/v2/repositories/${NAMESPACE}/${NAME}/tags/$1" \
    >/dev/null 2>&1
}

if hub_has_tag "$VERSION" && [[ "$FORCE" -eq 0 ]]; then
  log "tag ${IMAGE}:${VERSION} sudah ada di Docker Hub — tidak ada yang perlu di-push"
  exit 0
fi
log "tag ${IMAGE}:${VERSION} belum ada di Docker Hub (atau --force)"

# --- 3. working tree harus bersih --------------------------------------------
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "DILEWATI: working tree kotor (ada perubahan belum di-commit di ${REPO_DIR})"
  exit 2
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  log "DILEWATI: branch aktif '${CURRENT_BRANCH}', bukan main"
  exit 2
fi

log "fast-forward ke origin/main"
git merge --ff-only origin/main >/dev/null || die "tidak bisa fast-forward ke origin/main"

if [[ "$DRY_RUN" == "1" ]]; then
  log "DRY_RUN=1 — berhenti di sini (tidak build/push)"
  exit 0
fi

# --- 4. build + push ---------------------------------------------------------
log "build & push ${IMAGE}:${VERSION} (+ latest)"
bash scripts/push-dockerhub.sh "$VERSION"

if hub_has_tag "$VERSION"; then
  log "selesai: ${IMAGE}:${VERSION} dan ${IMAGE}:latest ada di Docker Hub"
else
  die "push selesai tapi tag ${VERSION} tidak terlihat di Docker Hub"
fi
