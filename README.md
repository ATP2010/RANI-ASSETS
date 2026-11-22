# RANI — Resource & Asset Network Intelligence

**RANI** = IT asset inventory self-hosted (mirip Lansweeper): agent **raniPush** di PC user
→ server FastAPI menangkap → dashboard AdminLTE realtime (WebSocket) + custom report SQL +
scan SNMP + port map L2 + manajemen user/role + Actions (gaya Lansweeper).

- GitHub: https://github.com/ATP2010/RANI-ASSETS
- Docker Hub image: `adhityatp/raniassets:<tag>` (https://hub.docker.com/repository/docker/adhityatp/raniassets)
- Dokumentasi lengkap: [`docs/`](docs/) (deploy, scan, users, actions, reports, agent Windows)
- Deploy tercepat: punya Portainer? paste [`Portainer/docker-compose.yml`](Portainer/docker-compose.yml) + 2 env → deploy (§2 Opsi A)
- Doktrin dev: [`DEVGUIDE.md`](DEVGUIDE.md) · Progres: [`CHECKLIST.md`](CHECKLIST.md)

---

## 1. Syarat new server (prasyarat)

Sebelum install, pastikan server memenuhi:

### Hardware
- **CPU**: 2 vCPU (disarankan 4 untuk scan SNMP + report SQL)
- **RAM**: ≥ 2 GB (disarankan 4 GB — Postgres + Redis + 2 worker uvicorn)
- **Disk**: ≥ 20 GB (Postgres data + raw payload retention 90 hari)
- **Arsitektur**: `linux/amd64` (image dibangun untuk amd64)

### Software
- **OS**: Ubuntu 22.04/24.04 (atau Debian 11/12, Rocky/Alma 8/9 — lihat `scripts/install-ubuntu.sh`)
- **Docker Engine** 20.10+ dengan **Compose v2** (`docker compose version`)
- **Portainer** 2.20+ (opsional, disarankan) — kalau sudah ada, deploy cukup dari
  Stack editor: paste stack + env, tanpa clone repo (lihat §2 Opsi A)
- Akses ke `registry-1.docker.io` (untuk pull image) dan repo image
- Port bebas: **80 & 443** (Caddy/HTTPS) atau **8091** (HTTP dev)
- Untuk scan SNMP: UDP 161 (atau port grup) terbuka dari server ke perangkat target

### Jaringan & domain (produksi)
- Domain publik dengan DNS A/AAAA → IP server (untuk HTTPS otomatis Let's Encrypt)
- Port 80 & 443 terbuka di firewall (`sudo ufw allow 80,443/tcp`)

### Kredensial yang perlu disiapkan
- Password DB (`POSTGRES_PASSWORD`) — generate: `openssl rand -hex 16`
- Password admin (`RANI_ADMIN_PASSWORD`)
- HMAC pepper (`RANI_INGEST_PEPPER`) — generate: `openssl rand -hex 32`
- Password role report (`RANI_REPORT_DB_PASSWORD`) — generate: `openssl rand -hex 16`
- (Produksi) `RANI_DOMAIN` + `RANI_ACME_EMAIL`

---

## 2. Deploy ke new server

Dua jalur, image sama (`adhityatp/raniassets:latest`), tanpa build di server:

- **Opsi A — Portainer** (disarankan kalau Portainer sudah ada): tempel stack, isi env, deploy.
  Tidak perlu clone repo, tidak perlu SSH ke host, tidak ada file yang di-copy.
- **Opsi B — tanpa Portainer**: installer satu perintah atau Docker Compose manual.

### Opsi A — Portainer: paste stack + env, lalu deploy

**Prasyarat**
- **Portainer 2.20+** dengan endpoint **Docker standalone** (bukan Swarm), sudah login.
- **Docker Engine** 20.10+ di host, arsitektur **linux/amd64**.
- **RAM** ≥ 2 GB (disarankan 4 GB), **disk** ≥ 20 GB.
- Port **80** bebas di host (Caddy). Port **443** juga, kalau mau HTTPS.
- Akses `registry-1.docker.io` dari server.
- (Opsional, untuk HTTPS) domain dengan DNS A/AAAA → IP server; port 80 reachable dari internet.

**Langkah (5 menit)**
1. Portainer → **Stacks** → **Add stack** → **Name**: `rani` → Build method: **Web editor**.
2. Tempel seluruh isi [`Portainer/docker-compose.yml`](Portainer/docker-compose.yml)
   (buka link → **Raw** → copy semua). Stack ini sengaja satu file: tanpa `env_file`,
   tanpa bind mount, Caddyfile ditulis inline saat container start.
3. Bagian **Environment variables** → **Advanced mode** → paste minimal 2 baris ini:

```
POSTGRES_PASSWORD=ganti-hex-16-karakter
RANI_ADMIN_PASSWORD=ganti-password-admin
```

   Opsional (biarkan kosong kalau akses masih lewat IP):

```
RANI_DOMAIN=rani.example.com
RANI_ACME_EMAIL=admin@example.com
TZ=Asia/Jakarta
```

   Alternatif: **Load variables from .env file** → upload
   [`.env.portainer.example`](Portainer/.env.portainer.example) yang sudah diisi
   (atau paste isinya). Daftar lengkap 40+ variabel ada di file itu.

4. Klik **Deploy the stack**. Urutan start: `db`/`redis` healthy → `api` menjalankan
   `alembic upgrade head` lalu uvicorn → `worker` konsumsi Redis → `caddy` di port 80.
   Siap ±30–60 detik (HTTPS butuh 30–60 detik tambahan untuk sertifikat Let's Encrypt).
5. Buka `http://<ip-server>/` (atau `https://<RANI_DOMAIN>/`) → login `admin` /
   `RANI_ADMIN_PASSWORD`.

**Env wajib vs otomatis**

| Variable | Status |
|---|---|
| `POSTGRES_PASSWORD` | **wajib** — huruf/angka saja: `openssl rand -hex 16` |
| `RANI_ADMIN_PASSWORD` | disarankan — kosong = password acak, dicetak di log `api` |
| `RANI_DOMAIN` + `RANI_ACME_EMAIL` | opsional — kosong = HTTP di port 80 |
| `RANI_INGEST_PEPPER` | otomatis — diturunkan dari `POSTGRES_PASSWORD` |
| `RANI_REPORT_DB_PASSWORD` | otomatis — diturunkan; menu Reports langsung aktif |
| 40+ var lain (scan, AD, actions, …) | default aman, tidak perlu diisi |

Catatan:
- **Jangan ganti `POSTGRES_PASSWORD` setelah ada data** — pepper agent & password role
  report diturunkan dari situ. Kalau harus ganti, isi `RANI_INGEST_PEPPER` manual dulu
  dengan nilai lama, baru ganti password.
- Jangan menambahkan `COMPOSE_PROJECT_NAME`; prefix container/volume ikut nama stack.
- Port `8091` default hanya listen di localhost. Mau expose langsung? set
  `RANI_BIND_IP=0.0.0.0`.
- Port 80/443 sudah dipakai NPM/Traefik/Caddy lain? Hapus service `caddy` dari stack,
  set `RANI_BIND_IP=0.0.0.0`, lalu arahkan proxy Anda ke `http://<ip-server>:8091`.

Panduan Portainer lengkap (HTTPS, backup/restore, troubleshooting, uninstall):
[`Portainer/README.md`](Portainer/README.md).

### Opsi B — tanpa Portainer

**Installer satu perintah** (install Docker, `/opt/rani`, systemd, health check):

```bash
sudo bash scripts/install-ubuntu.sh
# atau tanpa clone repo:
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/scripts/install-ubuntu.sh | sudo bash
```

**Manual (clone + compose)**

```bash
git clone https://github.com/ATP2010/RANI-ASSETS.git
cd RANI-ASSETS/ProjectDev
cp .env.hub.example .env
# edit .env: POSTGRES_PASSWORD, RANI_ADMIN_PASSWORD, RANI_INGEST_PEPPER,
#            RANI_REPORT_DB_PASSWORD, RANI_DOMAIN, RANI_ACME_EMAIL
docker compose -f docker-compose.hub.yml up -d                 # HTTP saja
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d   # HTTPS
```

**Tanpa clone (hanya pull image)**

```bash
mkdir -p /opt/rani && cd /opt/rani
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/docker-compose.hub.yml -o docker-compose.hub.yml
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/docker-compose.caddy.yml -o docker-compose.caddy.yml
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/.env.hub.example -o .env
# edit .env, lalu:
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d
```

Verifikasi: `curl -s http://127.0.0.1:8091/health` →
`{"status":"ok","db":true,"version":"0.1.0"}` — nilai `version` mengikuti tag image
yang di-pull (`latest` saat ini = 0.1.0).

### Setelah running
1. Buka `https://<RANI_DOMAIN>` (atau `http://<ip>:8091`) → redirect ke `/login`.
2. Login dengan `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD` dari env.
3. Cek cepat: Dashboard (0 aset kalau belum ada agent), Agents → Push (tombol download
   signed exe), Reports (3 contoh), Agents → Grup IP & OID.

### Upgrade versi (nanti)

**Portainer**: Stacks → `rani` → **Pull and redeploy** (centang re-pull image).

**Compose**:
```bash
cd /opt/rani
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml pull
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d
```

Migrasi DB jalan otomatis (`alembic upgrade head` di entrypoint `api`).

Dokumentasi lengkap: [`docs/deploy-dockerhub.md`](docs/deploy-dockerhub.md),
[`docs/deploy-caddy.md`](docs/deploy-caddy.md), [`Portainer/README.md`](Portainer/README.md).

---

## 3. Kelebihan RANI

- **Self-hosted, single image** — pull & run tanpa build, tanpa Python/Node di server.
  Image berisi API, worker, skema DB, migrasi, docs, skrip, dan artefak agent.
- **Agent Windows (`raniPush`)** — collect hardware/OS/software/security/users/network,
  push via Task Scheduler, spool offline, auto-register tanpa token (mode direct).
- **Dashboard realtime** — AdminLTE 4 + Apache ECharts (donut OS/status, bar top software,
  area push 24 jam WIB), WebSocket live update.
- **Sidebar mini persisten** — status collapse disimpan di localStorage.
- **Custom reports SQL** — user tulis SELECT, dieksekusi role DB read-only `rani_report`
  (guard SELECT-only, row cap, statement timeout, filter per kolom, export CSV).
- **Scan SNMP + custom OID** — grup IP (CIDR/range/IP), probe v1/v2c, asset `network`
  otomatis, port map L2 (MAC ↔ port switch dari bridge FDB), tab di asset, **jadwal scan
  otomatis per grup** (loop menit/jam atau jam tertentu + hari).
- **Port map L2** — `endpoint_port_mappings`, delta present/false, lookup MAC, halaman
  `/agents/portmap` + tab di asset network.
- **Users & akses (F5)** — login lokal (bcrypt) + AD (LDAP/LDAPS), role/permission
  custom (union multi-role, admin terkunci), connector AD, mapping group → role,
  sync delta + riwayat, sesi & audit.
- **Actions (gaya Lansweeper)** — hover hostname → popup overview + menu Actions
  (RDP, SSH, VNC, HTTP/HTTPS, share, salin); action script dieksekusi di PC pengguna
  via ekstensi Chromium + native host (tanpa admin di server).
- **Setup → Actions & Dashboard** — kelola action dan widget custom (sumber report SQL)
  dari UI; urutan/lebar/on-off/duplikat.
- **Reports & dashboard widget sebagai datatable** — search, sort, pagination,
  "X–Y dari Z" info, dropdown per halaman.
- **Bilingual (id/en)** — switcher di navbar (AdminLTE-style `#language-menu`),
  katalog 700+ key, fallback id.
- **Bilingual docs** — docs `.md` tersedia di `/docs/<slug>` (wajib login).
- **Ikon aplikasi** — favicon, apple-touch, manifest, logo sidebar; `scripts/make-icons.py`.
- **Deploy fleksibel** — Docker Hub pull & run, Caddy HTTPS otomatis, installer Ubuntu,
  registry lokal, GPO/SCCM untuk agent Windows.
- **Tanpa CDN/online** — ECharts, Bootstrap, AdminLTE vendored di image.
- **Keamanan** — HMAC ingest, nonce anti-replay, RBAC, audit log, report SQL read-only,
  bind password AD terenkripsi (Fernet), tidak ada tulis ke AD.

---

## 4. Problem solving (kasus umum)

### A. `/health` belum menjawab setelah `up -d`
- api masih migrasi/boot (±30–60 detik pertama). Cek `logs api`, tunggu, jangan restart.
- Migrasi gagal (DuplicateColumn) → pastikan image terbaru (sudah idempotent di 0005/0006).

### B. `pull access denied for adhityatp/raniassets`
- Repo private → `docker login -u adhityatp` dulu; atau tag salah (cek `docker images`).

### C. Menu Reports: "fitur report belum aktif"
- `RANI_REPORT_DB_PASSWORD` kosong di `.env` → isi, lalu `up -d` (restart api).

### D. Agent push gagal / 401
- Secret salah → 401; digest salah → 401; agent tak dikenal → 401; replay nonce → 409.
- Revoke agent → push 401. Cek log agent (`C:\ProgramData\Rani\raniPush.log`).
- Push gagal (server mati) → payload di-spool, dicoba lagi pada run berikutnya (maks 7 hari).

### E. Windows memblokir `raniPush.exe`
- SmartScreen: `Unblock-File .\raniPush.exe` atau "More info → Run anyway".
- Smart App Control enforce: gunakan **Jalur A (portable)** — `python.exe` resmi lolos.
- ASR/WDAC domain: minta IT allowlist publisher (CN=RANI Internal Code Signing) atau hash.
- Detail: [`docs/agent-windows.md` §8](docs/agent-windows.md#8-kalau-windows-memblokir-ranipushexe-smartscreen--smart-app-control).

### F. Scan SNMP: 0 host menjawab
- Cek community string, ACL SNMP di perangkat, UDP port grup. Probe sysObjectID timeout → tandai `timeout`.

### G. Login AD gagal
- `RANI_AD_ENABLED=0` → set 1 + restart.
- Tanpa mapping group → `no_mapped_group`. Petakan group AD → role di `/users/directory`.
- Rate-limit: 20× 401 → 429 (tunggu 5 menit).
- Bind password salah → sync `partial`, user tidak dinonaktifkan massal.

### H. Sesi/cert
- HTTPS: cek DNS A record + port 80 terbuka (Let's Encrypt HTTP-01). Lihat `docker compose logs caddy`.
- Port 8091 terbuka langsung di produksi → set `RANI_HTTP_PORT=127.0.0.1:8091`.

### I. Database / migrasi
- Backup: `pg_dump` harian ke volume (belum otomatis — backlog F3.7).
- Rollback: set `RANI_IMAGE` ke tag lama → `pull` → `up -d`. Kalau migrasi baru sudah ubah schema, restore dari backup.

### J. Lain-lain
- Compose project name bentrok dengan stack lama `/root/rani` (project `rani`, port 8088/8443) → ProjectDev memakai `rani-inv`, jangan ubah.
- `.env` gitignored — jangan commit password/pepper. `.env.secrets` juga gitignored + dockerignored.
- Pepper berubah → agent lama & community tersimpan tidak bisa didekripsi (agent harus push ulang / community diisi ulang).

---

## Struktur

```
ProjectDev/
├── docker-compose.yml      api, worker, postgres 16.4, redis 7.4 (project rani-inv)
├── docker-compose.hub.yml  pull & run dari Docker Hub (tanpa build)
├── docker-compose.caddy.yml overlay HTTPS (Caddy)
├── Caddyfile               reverse proxy + TLS otomatis
├── Portainer/              stack siap-paste untuk Portainer (compose + env contoh + README)
├── .env.example / .env.hub.example / .env.secrets
├── schema/agent_payload_v1.json   kontrak payload agent (versioned)
├── agent/raniPush.py       collector+pusher Windows/Linux (stdlib)
├── server/app/             FastAPI: api/, ingest/, templates/, static/
├── server/worker/          konsumen Redis Stream + requeue + stale sweep
├── db/                     alembic (0001–0013, idempotent fresh install & upgrade)
├── server/tests/           unit test murni
├── scripts/                build, push, install, sign, smoke test
├── docs/                   deploy, scan, users, actions, reports, branding, agent-windows
└── .github/workflows/      build-agent-exe, push-dockerhub
```

## Dokumentasi lengkap

- [`docs/overview.md`](docs/overview.md) — dokumentasi terkonsolidasi
- [`docs/analysis.md`](docs/analysis.md) — requirements & analisis
- [`docs/deploy-dockerhub.md`](docs/deploy-dockerhub.md) — deploy dari Docker Hub
- [`docs/deploy-caddy.md`](docs/deploy-caddy.md) — deploy dengan Caddy/HTTPS
- [`Portainer/README.md`](Portainer/README.md) — deploy via Portainer (stack siap-paste)
- [`docs/agent-windows.md`](docs/agent-windows.md) — agent Windows
- [`docs/scan.md`](docs/scan.md) — scan SNMP + custom OID
- [`docs/users.md`](docs/users.md) — Users, role/permission, AD
- [`docs/actions.md`](docs/actions.md) — Actions ala Lansweeper
- [`docs/reports.md`](docs/reports.md) — custom report SQL
- [`docs/branding.md`](docs/branding.md) — logo/ikon

## Keamanan singkat

- Agent auth: `HMAC-SHA256(agent_secret, timestamp+nonce+body)` + `sha256(body)` digest,
  toleransi skew 300s, nonce anti-replay di Redis. Secret disimpan terenkripsi (Fernet,
  key turunan `RANI_INGEST_PEPPER`).
- Tidak ada TLS wajib (LAN by-IP, keputusan owner ADR-D2); HMAC tetap jalan tanpa TLS.
  Untuk produksi/internet: gunakan Caddy (HTTPS otomatis).
- UI: session cookie HttpOnly + bcrypt + RBAC (`admin` > `operator` > `reader`), audit log.
- `.env` / `.env.secrets` gitignored — jangan pernah commit password/pepper.

## Lisensi

Proprietary — lihat `org.opencontainers.image.licenses` di Dockerfile.