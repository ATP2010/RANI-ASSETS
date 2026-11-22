# RANI — Resource & Asset Network Intelligence

Self-hosted IT asset inventory for Windows/Linux endpoints and SNMP network gear —
an open, LAN-first alternative to Lansweeper. One image contains the API, the ingest
worker, the database schema/migrations, the web UI, the documentation, and the agent
binaries.

- **Agent** `raniPush` pushes hardware / software / OS / network / security inventory
- **Realtime dashboard** (AdminLTE 4 + Apache ECharts + WebSocket)
- **Custom reports** — user-written `SELECT` executed by a separate read-only DB role
- **Network scan** — SNMP v1/v2c sweeps per IP group, with Lansweeper-style custom OIDs
- **Layer-2 port map** — MAC ↔ switch port from the bridge forwarding table (dot1d/dot1q),
  linked to known assets, with a MAC lookup
- **No cloud dependency** — everything stays on your LAN; Postgres + Redis only

**Users & access (F5, included):** local accounts plus Active Directory (LDAP/LDAPS)
group sync, custom roles with granular permissions, and session/audit management.
Design: `docs/users.md` (in-app: `/docs/users`).

---

## What runs

| Service | Image | Purpose |
|---|---|---|
| `api` | this image | FastAPI + Alembic migrations + web UI (port 8000 → published 8091) |
| `worker` | this image | ingests agent pushes from Redis Stream into Postgres |
| `db` | `postgres:16.4-alpine` | inventory data (volume `pgdata`) |
| `redis` | `redis:7.4-alpine` | ingest queue + realtime events (volume `redisdata`) |

The image also serves the documentation at `/docs/<slug>` and the signed Windows agent at
`/agents/push` (no external download needed).

## Quick start

```bash
mkdir -p /opt/rani && cd /opt/rani

cat > docker-compose.yml <<'YAML'
name: ${COMPOSE_PROJECT_NAME:-rani}

x-server: &server
  image: ${RANI_IMAGE:-adhityatp/raniassets:latest}
  env_file: [.env]
  environment:
    TZ: ${TZ:-Asia/Jakarta}
    DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-rani}:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-rani}
    REDIS_URL: redis://redis:6379/0
  restart: unless-stopped

services:
  db:
    image: postgres:16.4-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-rani}
      POSTGRES_USER: ${POSTGRES_USER:-rani}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
      TZ: ${TZ:-Asia/Jakarta}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-rani} -d ${POSTGRES_DB:-rani}"]
      interval: 5s
      timeout: 3s
      retries: 20
    networks: [internal]

  redis:
    image: redis:7.4-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory-policy", "noeviction"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20
    volumes: [redisdata:/data]
    networks: [internal]

  api:
    <<: *server
    command: sh -c "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers 2"
    ports: ["${RANI_HTTP_PORT:-8091}:8000"]
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
    networks: [edge, internal]

  worker:
    <<: *server
    command: ["python", "-m", "worker.worker"]
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
      api: {condition: service_started}
    networks: [internal]

networks:
  edge: {driver: bridge}
  internal: {driver: bridge, internal: true}
volumes:
  pgdata:
  redisdata:
YAML

cat > .env <<'ENV'
RANI_IMAGE=adhityatp/raniassets:v0.1.0
RANI_HTTP_PORT=8091
TZ=Asia/Jakarta
POSTGRES_DB=rani
POSTGRES_USER=rani
POSTGRES_PASSWORD=change-me-db
RANI_ADMIN_USER=admin
RANI_ADMIN_PASSWORD=change-me-admin
RANI_INGEST_PEPPER=replace-with-openssl-rand-hex-32
RANI_REPORT_DB_PASSWORD=replace-with-openssl-rand-hex-16
RANI_TOKENLESS_PUSH=1
RANI_ENV=production
ENV

docker compose pull
docker compose up -d
curl -s http://127.0.0.1:8091/health     # {"status":"ok","db":true,...}
```

Open `http://<server>:8091` and log in with `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD`
(seeded on first boot). First start takes ~30–60 s because migrations run.

### Install the agent (no token needed)

1. UI → **Agents → Push** → download `raniPush-signed.exe`
2. On Windows (PowerShell as Administrator):

```powershell
Unblock-File .\raniPush-signed.exe
.\raniPush-signed.exe <server-ip>:8091
schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f ^
  /tr "C:\Rani\raniPush-signed.exe <server-ip>:8091"
```

The server identifies the PC by `machine_id`; the first push auto-registers the agent.
Set `RANI_TOKENLESS_PUSH=0` to require enrollment tokens + HMAC instead.

### Scan network gear (SNMP)

UI → **Agents → Grup IP & OID**: add a group (CIDR / range / single IP, SNMP v1/v2c,
community, port), optionally add custom OIDs (`label` + OID, suffix `.*` walks a table),
then **Agents → Scan** → start. Devices that answer become `network` assets.

For switches, leave **Kumpulkan port map** checked: the scan reads the bridge forwarding
table (BRIDGE-MIB / Q-BRIDGE-MIB) and fills **Agents → Port map** with MAC ↔ port rows.
MACs that match a known asset's primary MAC are linked; unknown MACs are shown but never
turned into new assets.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RANI_IMAGE` | `adhityatp/raniassets:latest` | image tag to run |
| `RANI_HTTP_PORT` | `8091` | published UI port |
| `POSTGRES_PASSWORD` | — | **required**; DB password (URL-safe characters) |
| `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD` | `admin` / random | admin seeded when the user table is empty |
| `RANI_INGEST_PEPPER` | dev value | encrypts agent secrets / SNMP communities; **set once** |
| `RANI_REPORT_DB_PASSWORD` | — | password for the read-only report role; empty disables `/reports` execution |
| `RANI_TOKENLESS_PUSH` | `1` | `0` = force enrollment token + HMAC |
| `RANI_SCAN_MAX_HOSTS` / `RANI_SCAN_CONCURRENCY` / `RANI_SCAN_TIMEOUT_S` | `512` / `16` / `1.0` | SNMP scan limits |
| `RANI_SCAN_FDB_ENABLED` / `RANI_SCAN_FDB_MAX` / `RANI_SCAN_FDB_UPLINK_MACS` | `1` / `2000` / `10` | port map: global switch, MAC cap per device, uplink hint threshold |
| `RANI_SCAN_SCHEDULER_TICK_S` / `RANI_SCAN_SCHEDULE_MIN_INTERVAL_MIN` / `RANI_SCHEDULE_TZ` | `30` / `5` / `Asia/Jakarta` | auto scan schedule: tick interval, loop min, schedule timezone |
| `RANI_SESSION_TTL_H` | `12` | login session lifetime (hours) |
| `RANI_AUTH_LOCAL_ENABLED` / `RANI_AD_ENABLED` / `RANI_AD_SYNC_INTERVAL_S` | `1` / `0` / `3600` | local/AD login switch, sync interval; bind password is stored encrypted in the DB, not in `.env` |
| `RANI_REPORT_MAX_ROWS` / `RANI_REPORT_TIMEOUT_MS` | `1000` / `8000` | custom report limits |
| `RANI_ENV` | `production` | `production` hides `/api/docs` |
| `TZ` | `Asia/Jakarta` | container timezone (UI shows WIB) |

Generate secrets:

```bash
openssl rand -hex 32   # RANI_INGEST_PEPPER
openssl rand -hex 16   # RANI_REPORT_DB_PASSWORD, POSTGRES_PASSWORD
```

## Data, backup, update

- Data lives in the `pgdata` volume; `docker compose down` keeps it, `down -v` deletes it.
- Backup: `docker compose exec -T db pg_dump -U rani -d rani -Fc > rani-$(date +%F).dump`
- Update: change `RANI_IMAGE` to a new tag → `docker compose pull && docker compose up -d`
  (migrations run automatically, volumes untouched).

## Security model

- LAN-first HTTP by default; put a TLS reverse proxy in front for untrusted networks.
- Agent push: body digest + nonce + timestamp are always verified; HMAC signature is used
  when the agent was enrolled. Tokenless mode trusts the LAN (toggle with `RANI_TOKENLESS_PUSH`).
- Custom reports run as a separate Postgres role with `default_transaction_read_only=on`,
  SELECT-only grants, statement timeout, row cap; credential tables are revoked.
- SNMP credentials are encrypted at rest; the scanner only issues GET/GETNEXT/GETBULK
  (no SET/write). Bridge FDB rows are stored as MAC ↔ port summaries, not raw dumps.
- Every write action and scan/report run is written to `audit_logs`.

## Tags

- `v0.1.0` — first public build (agent 0.2 tokenless push, ECharts dashboard, custom
  reports, SNMP scan, Docker Hub deployment)
- `latest` — points at the newest published build; pin a version tag in production

## Included documentation

Served in-app (login required): `/docs/agent-windows`, `/docs/scan`, `/docs/users`,
`/docs/reports`, `/docs/branding`, `/docs/deploy-dockerhub`.

## Requirements

- Docker Engine 20.10+ with Compose v2, linux/amd64, ≥2 GB RAM
- Outbound access to Docker Hub for `postgres`/`redis` images (first run only)

## Source / support

Built for internal IT operations. Image contains no telemetry and makes no outbound
connections; all traffic is between services in the compose network and your LAN.

For deployment details, troubleshooting, and the full compose file see
`docs/deploy-dockerhub.md` (also available inside the app at `/docs/deploy-dockerhub`).