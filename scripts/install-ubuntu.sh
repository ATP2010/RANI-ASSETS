#!/usr/bin/env bash
# RANI — installer untuk Ubuntu 22.04/24.04.
# Jalankan sebagai root:  sudo bash install-ubuntu.sh
# Atau: curl -fsSL https://.../install-ubuntu.sh | sudo bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/rani}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-rani}"
BASE_URL="${RANI_INSTALL_BASE_URL:-https://raw.githubusercontent.com/adhityatp/raniassets/main}"

log() { printf '\033[1;32m[rani]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[rani]\033[0m %s\n' "$*" >&2; }

# --- 0. root check ---
if [[ $EUID -ne 0 ]]; then
    err "Jalankan sebagai root (sudo)."; exit 1
fi

# --- 1. Docker ---
if ! command -v docker >/dev/null 2>&1; then
    log "Install Docker Engine..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# --- 2. Direktori ---
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# --- 3. Ambil file (lokal bila script dijalankan dari repo, else download) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo '')"
fetch() {
    local name="$1"
    if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/$name" ]]; then
        cp "$SCRIPT_DIR/$name" "$INSTALL_DIR/$name"
    elif [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../$name" ]]; then
        cp "$SCRIPT_DIR/../$name" "$INSTALL_DIR/$name"
    else
        curl -fsSL "$BASE_URL/$name" -o "$INSTALL_DIR/$name"
    fi
}

log "Menyiapkan file compose & Caddy..."
fetch docker-compose.hub.yml
fetch docker-compose.caddy.yml
fetch Caddyfile

if [[ ! -f .env ]]; then
    if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/.env.hub.example" ]]; then
        cp "$SCRIPT_DIR/.env.hub.example" .env
    elif [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../.env.hub.example" ]]; then
        cp "$SCRIPT_DIR/../.env.hub.example" .env
    else
        fetch .env.hub.example
        mv .env.hub.example .env
    fi
    # generate secret otomatis
    gen() { openssl rand -hex "$1"; }
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(gen 16)/" .env
    sed -i "s/^RANI_ADMIN_PASSWORD=.*/RANI_ADMIN_PASSWORD=$(gen 12)/" .env
    sed -i "s/^RANI_INGEST_PEPPER=.*/RANI_INGEST_PEPPER=$(gen 32)/" .env
    sed -i "s/^RANI_REPORT_DB_PASSWORD=.*/RANI_REPORT_DB_PASSWORD=$(gen 16)/" .env
    # domain placeholder: biarkan user isi nanti
    log ".env dibuat dengan secret acak. Edit RANI_DOMAIN & RANI_ACME_EMAIL sebelum HTTPS."
else
    log ".env sudah ada — tidak ditimpa."
fi

# --- 4. Firewall hint ---
if command -v ufw >/dev/null 2>&1; then
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
fi

# --- 5. Jalankan ---
log "Pull image & start stack..."
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml --project-name "$COMPOSE_PROJECT" pull
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml --project-name "$COMPOSE_PROJECT" up -d

# --- 6. Systemd unit (auto-start on boot) ---
cat > /etc/systemd/system/rani.service <<EOF
[Unit]
Description=RANI stack (docker compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml --project-name $COMPOSE_PROJECT up -d
ExecStop=/usr/bin/docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml --project-name $COMPOSE_PROJECT down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable rani.service

# --- 7. Health check ---
log "Menunggu health..."
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1/health >/dev/null 2>&1; then
        log "Sehat."
        break
    fi
    sleep 3
done

DOMAIN="$(grep -E '^RANI_DOMAIN=' .env | cut -d= -f2-)"
ADMIN="$(grep -E '^RANI_ADMIN_USER=' .env | cut -d= -f2-)"
PASS="$(grep -E '^RANI_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
echo
log "Selesai. Akses:"
echo "  https://${DOMAIN:-<domain-anda>}/   (set RANI_DOMAIN & RANI_ACME_EMAIL di .env lalu: systemctl restart rani)"
echo "  atau http://<ip-server>:8091/ untuk mode tanpa Caddy"
echo "  Login: ${ADMIN:-admin} / ${PASS:-<lihat .env>}"
echo "  Folder: $INSTALL_DIR"
echo "  Service: systemctl status rani"
