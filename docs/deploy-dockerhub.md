# Deploy dari Docker Hub (pull & run)

Panduan memindahkan RANI ke server dev hanya dengan **pull image** dari Docker Hub:
tidak perlu clone repo, build, Python, atau Node. Image berisi API, worker, skema DB,
migrasi, dokumen, skrip, dan artefak agent (raniPush-signed.exe, cert, portable zip).

- Image: `adhityatp/raniassets:v0.1.0` (+ `:latest`) — repo **public**
- Digest v0.1.0: `sha256:06f96852f887349c9d36426d8e4dcaafdc763b65d6bcc20d01974bb43a47215c`
- Yang tetap di host: file `docker-compose.hub.yml` + `.env`, volume Postgres/Redis
- Arsitektur image: **linux/amd64** (dibangun di server ini)
- Ukuran image: ±386 MB (termasuk exe 7,4 MB + portable zip 11 MB)

## 0. Apa yang ada di dalam image vs di host

| Bagian | Lokasi | Keterangan |
|---|---|---|
| API + worker (kode Python) | image | satu image, dua service beda `command` |
| Skema + migrasi Alembic (`0001`–`0004`) | image | dijalankan otomatis saat start api |
| Dokumen (`docs/*.md`) | image → `/srv/docs` | dibaca halaman `/docs/<slug>` |
| Artefak agent (exe signed, cert, zip) | image → `/srv/release` | tombol download di `/agents/push` |
| Skrip (`install-cert.ps1` dll) | image → `/srv/scripts` | download dari UI |
| Postgres 16.4 + Redis 7.4 | image resmi Docker Hub | di-pull otomatis oleh compose |
| Data (aset, user, laporan) | volume `pgdata` + `redisdata` | bertahan walau container diganti |
| Konfigurasi & password | `.env` di host | **jangan** commit / jangan taruh di image |

Halaman di aplikasi: `/` dashboard, `/assets`, `/agents/push`, `/agents/scan`,
`/agents/groups`, `/reports`, `/docs/<slug>`.

## 1. Prasyarat server dev

- Docker Engine 20.10+ dengan Compose v2 (`docker compose version`).
- Akses ke `registry-1.docker.io` (untuk pull) dan ke repo image.
- Port bebas untuk UI (default **8091**) — bisa diganti lewat `.env`.
- RAM disarankan ≥2 GB (Postgres + Redis + 2 worker uvicorn).
- Untuk scan SNMP: UDP 161 (atau port grup) terbuka dari server ke perangkat target.
- OS host: apa pun yang bisa menjalankan Docker (image berbasis Debian slim).

## 2. Siapkan folder deployment

```bash
mkdir -p /opt/rani && cd /opt/rani
```

Ambil dua file dari mesin ini (server lama) **atau** dari GitHub (repo publik):

```bash
# dari server lama (SSH)
scp root@192.168.88.92:/root/RaniProject/ProjectDev/docker-compose.hub.yml .
scp root@192.168.88.92:/root/RaniProject/ProjectDev/.env.hub.example .

# ATAU dari GitHub (tanpa SSH)
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/docker-compose.hub.yml -o docker-compose.hub.yml
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/.env.hub.example -o .env.hub.example
```

Kalau tidak ada akses SSH, salin isi kedua file dari lampiran di bawah (bagian 11).

## 2b. Satu perintah (installer otomatis)

Untuk server baru, cukup jalankan installer yang menangani semuanya (Docker, compose,
Caddy/HTTPS, secret, systemd):

```bash
sudo bash scripts/install-ubuntu.sh
# atau tanpa clone repo:
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/scripts/install-ubuntu.sh | sudo bash
```

Installer akan: install Docker, siapkan `/opt/rani`, generate secret, pull image,
`up -d` (api+worker+postgres+redis+caddy), pasang systemd unit `rani.service`,
health check, dan cetak URL + kredensial admin. Panduan lengkap: `docs/deploy-caddy.md`.

> Nama folder menentukan nama project Compose (prefix container & volume). Kalau di
> server itu sudah ada stack RANI lain, jangan pakai folder yang sama, atau set
> `COMPOSE_PROJECT_NAME` di `.env` (mis. `rani-prod`) supaya volume tidak tertukar.

## 3. Buat `.env`

```bash
cp .env.hub.example .env
```

Isi minimal yang **wajib** diganti:

```bash
# generate nilai acak
openssl rand -hex 16     # → POSTGRES_PASSWORD
openssl rand -hex 32     # → RANI_INGEST_PEPPER
openssl rand -hex 16     # → RANI_REPORT_DB_PASSWORD
```

Lalu edit `.env`:

```ini
POSTGRES_PASSWORD=<hasil rand 16>
RANI_ADMIN_PASSWORD=<password admin pilihan Anda>
RANI_INGEST_PEPPER=<hasil rand 32>
RANI_REPORT_DB_PASSWORD=<hasil rand 16>
RANI_IMAGE=adhityatp/raniassets:v0.1.0     # pakai tag spesifik, bukan latest
RANI_HTTP_PORT=8091
TZ=Asia/Jakarta
```

Aturan penting:

- `POSTGRES_PASSWORD` dan password lain sebaiknya **huruf/angka** (aman URL). Kalau ada
  karakter khusus, password DB ikut dipakai di `DATABASE_URL` dan harus URL-encoded.
- `RANI_INGEST_PEPPER` mengunci enkripsi secret agent & community SNMP. Kalau diganti,
  data terenkripsi lama tidak bisa dibaca (agent harus push ulang / community diisi ulang).
- `RANI_ADMIN_PASSWORD` hanya dipakai saat **boot pertama** ketika tabel user masih kosong.
- Jangan mengekspor variabel `.env` ke shell sesi (`set -a; . ./.env`). Compose
  memprioritaskan environment shell di atas `.env` — nilai lama bisa "menang" dan
  menyebabkan password/port salah. Cukup andalkan `.env`.

## 4. Pull & jalankan

```bash
cd /opt/rani
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

Urutan yang terjadi saat start:

1. `db` (Postgres 16.4) dan `redis` (7.4) start + healthcheck.
2. `api` menjalankan `alembic upgrade head` (membuat schema `rani_inventory`, 4 migrasi),
   membuat role DB read-only `rani_report` untuk menu Reports, mengisi 3 report contoh,
   lalu uvicorn 2 worker di port 8000 (dipublish ke 8091).
3. `worker` mulai mengonsumsi antrean ingest (Redis Stream).

Cek status dan kesehatan:

```bash
docker compose -f docker-compose.hub.yml ps
curl -s http://127.0.0.1:8091/health
# {"status":"ok","db":true,"version":"0.1.0"}
```

Kalau `/health` belum menjawab, tunggu ±30–60 detik (migrasi pertama) lalu cek log:

```bash
docker compose -f docker-compose.hub.yml logs -f api
```

## 5. Login pertama

1. Buka `http://<ip-server>:8091` → redirect ke `/login`.
2. Masuk dengan `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD` dari `.env`.
3. Cek cepat:
   - **Dashboard** menampilkan kartu aset (0 kalau belum ada agent).
   - **Agents → Push** menampilkan tombol download `raniPush-signed.exe` (7,33 MB).
   - **Reports** sudah berisi 3 contoh; klik **Jalankan** pada salah satunya → hasil grid.
   - **Agents → Grup IP & OID** siap untuk scan SNMP.

Ganti password admin (opsional tapi disarankan; tidak ada menu ubah password):

```bash
docker compose -f docker-compose.hub.yml exec api python - <<'PY'
from app.db import SessionLocal
from app.models import AppUser
from app.security import hash_password
import asyncio, os, getpass

new = os.environ.get("NEW_ADMIN_PASSWORD") or getpass.getpass("password baru: ")

async def main():
    async with SessionLocal() as s:
        from sqlalchemy import select
        user = (await s.execute(select(AppUser).where(
            AppUser.username == os.environ.get("RANI_ADMIN_USER", "admin")))).scalar_one()
        user.password_hash = hash_password(new)
        await s.commit()
        print("password admin diperbarui:", user.username)

asyncio.run(main())
PY
```

## 6. Pasang agent di PC Windows

1. Di UI: **Agents → Push** → **Download** `raniPush-signed.exe`.
2. PowerShell as Administrator:

```powershell
cd C:\Rani
Unblock-File .\raniPush-signed.exe
.\raniPush-signed.exe <ip-server>:8091
schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f ^
  /tr "C:\Rani\raniPush-signed.exe <ip-server>:8091"
```

Tidak ada token/enroll (default `RANI_TOKENLESS_PUSH=1`). Panduan lengkap:
tombol **Panduan lengkap Windows** di halaman itu atau `docs/agent-windows.md`.

## 7. Update ke versi/tag baru

```bash
cd /opt/rani
# 1. ganti RANI_IMAGE di .env ke tag baru, mis. adhityatp/raniassets:0.2.0
docker compose -f docker-compose.hub.yml pull
docker compose -f docker-compose.hub.yml up -d
```

`up -d` akan recreate container yang image-nya berubah; **volume tidak dihapus**.
Migrasi baru dijalankan otomatis oleh service api saat start.

Rollback: set `RANI_IMAGE` kembali ke tag lama → `pull` → `up -d`. Kalau migrasi versi baru
sudah mengubah schema dan rollback butuh schema lama, restore dari backup (bagian 9).

## 8. Operasional harian

```bash
cd /opt/rani
docker compose -f docker-compose.hub.yml ps                 # status
docker compose -f docker-compose.hub.yml logs -f api        # log API
docker compose -f docker-compose.hub.yml logs -f worker     # log ingest
docker compose -f docker-compose.hub.yml restart api        # restart saja
docker compose -f docker-compose.hub.yml down               # stop (volume tetap)
docker compose -f docker-compose.hub.yml down -v            # stop + HAPUS data (hati-hati)
```

Port & firewall: UI hanya butuh TCP 8091 (atau `RANI_HTTP_PORT`). Jangan buka Postgres/
Redis ke luar — keduanya di network `internal` dan tanpa `ports`.

**HTTPS (produksi):** taruh Caddy di depan 8091 dengan overlay `docker-compose.caddy.yml`
(sertifikat otomatis via Let's Encrypt). Panduan lengkap: [`docs/deploy-caddy.md`](deploy-caddy.md).

```bash
# di folder /opt/rani, set di .env:
RANI_DOMAIN=rani.example.com
RANI_ACME_EMAIL=admin@example.com
# lalu jalankan:
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d
```

Atau gunakan installer satu perintah (sudah termasuk Caddy):
```bash
sudo bash scripts/install-ubuntu.sh
```

Kalau perlu HTTPS, aplikasi sudah memakai `--proxy-headers`.

## 9. Backup & restore

Backup database (harian, simpan di luar volume):

```bash
mkdir -p /var/backups/rani
docker compose -f docker-compose.hub.yml exec -T db \
  pg_dump -U rani -d rani -Fc > /var/backups/rani/rani-$(date +%F).dump
```

Restore ke instalasi baru (DB harus kosong / sudah dimigrasi):

```bash
docker compose -f docker-compose.hub.yml stop api worker
docker compose -f docker-compose.hub.yml exec -T db \
  pg_restore -U rani -d rani --clean --if-exists < /var/backups/rani/rani-2026-11-14.dump
docker compose -f docker-compose.hub.yml start api worker
```

Volume Redis hanya antrean sementara; aman dikosongkan (report yang belum diproses akan
di-requeue dari tabel `software_reports`).

## 10. Troubleshooting

| Gejala | Penyebab / solusi |
|---|---|
| `Bind for 0.0.0.0:8091 failed: port is already allocated` | port dipakai proses/stack lain (mis. stack dev lama). Ganti `RANI_HTTP_PORT` di `.env`, atau hentikan stack lama |
| `/health` 502/connection reset setelah `up -d` | api masih migrasi/boot (±40 dtk pertama). Cek `logs api`; tunggu, jangan langsung restart |
| `password authentication failed for user "rani"` | `POSTGRES_PASSWORD` berubah setelah volume dibuat. Password lama tersimpan di volume: pakai password lama, atau `down -v` (hapus data) untuk instalasi baru |
| Nilai `.env` tidak terpakai | ada environment shell bernama sama (`RANI_*`, `POSTGRES_*`). Jalankan `env | grep -E '^(RANI|POSTGRES)_'` lalu `unset` atau buka shell baru |
| `pull access denied for adhityatp/raniassets` | repo private → `docker login -u adhityatp` dulu; atau tag salah |
| Menu Reports: "fitur report belum aktif" | `RANI_REPORT_DB_PASSWORD` kosong di `.env` → isi, lalu `up -d` (restart api) |
| Reports: `permission denied for table ...` | tabel kredensial memang diblokir; atau role `rani_report` belum dibuat karena api tidak punya hak superuser (jangan ubah `POSTGRES_USER`) |
| Scan SNMP 0 ditemukan | SNMP belum aktif/community salah/ACL perangkat. Uji dari server: `snmpget -v2c -c <community> <ip> 1.3.6.1.2.2.0` |
| Tombol download exe "belum tersedia" | image dibuild tanpa `release/` (artefak tidak ada saat build). Rebuild di mesin build, atau taruh file di volume `/srv/release` |
| `exec format error` saat start | image amd64 di host ARM. Build ulang untuk arm64 (`docker buildx`) |
| Data hilang setelah `down` | `down` tidak menghapus volume; hanya `down -v` yang menghapus. Cek `docker volume ls | grep pgdata` |

## 11. Lampiran

### 11.1 `docker-compose.hub.yml`

```yaml
name: ${COMPOSE_PROJECT_NAME:-rani}

x-server: &server
  image: ${RANI_IMAGE:-adhityatp/raniassets:latest}
  env_file: [.env]
  environment:
    TZ: ${TZ:-Asia/Jakarta}
    DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-rani}:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}@db:5432/${POSTGRES_DB:-rani}
    REDIS_URL: redis://redis:6379/0
  restart: unless-stopped

services:
  db:
    image: postgres:16.4-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-rani}
      POSTGRES_USER: ${POSTGRES_USER:-rani}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      TZ: ${TZ:-Asia/Jakarta}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-rani} -d ${POSTGRES_DB:-rani}"]
      interval: 5s
      timeout: 3s
      retries: 20
    networks: [internal]
    restart: unless-stopped

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
    restart: unless-stopped

  api:
    <<: *server
    command:
      - sh
      - -c
      - alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers 2
    ports:
      - "${RANI_HTTP_PORT:-8091}:8000"
    depends_on:
      db: {condition: service_healthy}
      redis: {condition: service_healthy}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 40s
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
```

### 11.2 `.env.hub.example`

Lihat file di repo: `.env.hub.example` (semua variabel + komentar). Ringkasnya:

```ini
RANI_IMAGE=adhityatp/raniassets:latest
COMPOSE_PROJECT_NAME=rani
RANI_HTTP_PORT=8091
TZ=Asia/Jakarta
POSTGRES_DB=rani
POSTGRES_USER=rani
POSTGRES_PASSWORD=...
RANI_ADMIN_USER=admin
RANI_ADMIN_PASSWORD=...
RANI_INGEST_PEPPER=...            # openssl rand -hex 32
RANI_REPORT_DB_PASSWORD=...       # openssl rand -hex 16
RANI_TOKENLESS_PUSH=1
RANI_ENV=production
RANI_SESSION_TTL_H=12
RANI_AUTH_LOCAL_ENABLED=1
# Set 1 setelah ada connector AD terpetakan ke role admin (lihat docs/users.md):
RANI_AD_ENABLED=0
RANI_AD_SYNC_INTERVAL_S=3600
RANI_PASSWORD_MIN_LEN=12
RANI_LOGIN_MAX_ATTEMPTS=20
```

### 11.3 Checklist "pull sampai running"

- [ ] Folder baru, tidak bentrok dengan stack lama (`COMPOSE_PROJECT_NAME` unik)
- [ ] `docker-compose.hub.yml` + `.env` ada, password/pepper sudah diganti
- [ ] Tidak ada `RANI_*`/`POSTGRES_*` yang ter-export di shell
- [ ] `docker compose -f docker-compose.hub.yml pull` sukses
- [ ] `up -d` → `ps` menunjukkan db/redis healthy, api/worker up
- [ ] `curl /health` → `{"status":"ok","db":true}`
- [ ] Login admin berhasil; dashboard tampil
- [ ] `/agents/push` menampilkan tombol download signed exe (7,33 MB)
- [ ] `/reports` berisi 3 contoh dan salah satu bisa **Jalankan**
- [ ] `/agents/groups` bisa menyimpan grup IP (community terenkripsi)
- [ ] Agent Windows push → aset muncul di `/assets`
- [ ] Backup `pg_dump` sudah dijadwalkan
- [ ] (Produksi) reverse proxy + HTTPS di depan port UI