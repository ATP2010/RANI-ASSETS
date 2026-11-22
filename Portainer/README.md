# RANI — deploy via Portainer

Stack Portainer untuk menjalankan RANI tanpa clone repo dan tanpa build:
API, worker, PostgreSQL, Redis, dan Caddy (HTTP sekarang, HTTPS saat domain
diisi) dalam satu file.

| File | Keterangan |
|---|---|
| `docker-compose.yml` | Stack utama untuk **Portainer → Stacks → Web editor** |
| `.env.portainer.example` | Daftar environment variable untuk di-import/diisi di UI Portainer |
| `README.md` | Dokumen ini |

Image yang dipakai: `adhityatp/raniassets:latest` (bisa diganti lewat `RANI_IMAGE`).
Image sudah memuat kode API, worker, migrasi DB, dokumentasi, skrip, dan artefak
agent (`raniPush-signed.exe`), jadi **tidak ada bind mount** yang diperlukan.

> **Cukup isi 2 nilai:** `POSTGRES_PASSWORD` dan `RANI_ADMIN_PASSWORD`.
> Akses awal lewat IP (`http://<ip-server>/`, port 80 via Caddy). HTTPS bisa
> diaktifkan kapan saja dengan mengisi `RANI_DOMAIN` — tanpa mengubah compose.

---

## 1. Prasyarat

- **Portainer** 2.20+ dengan endpoint **Docker standalone** (bukan Swarm).
- Host **linux/amd64** (image belum tersedia untuk arm64).
- Docker Engine 20.10+.
- RAM ≥ 2 GB (disarankan 4 GB), disk ≥ 20 GB.
- Port **80** bebas di host (dipakai Caddy). Port **443** juga, kalau nanti
  mengaktifkan HTTPS.
- Domain **opsional**. Untuk HTTPS: domain dengan DNS A/AAAA mengarah ke IP
  server, port 80 bisa diakses dari internet (HTTP-01 challenge Let's Encrypt).
- Akses ke `registry-1.docker.io` dari server.

Kalau port 80/443 sudah dipakai reverse proxy lain (NPM, Traefik, Caddy lain),
jangan pakai stack ini apa adanya — matikan service `caddy` dan arahkan proxy
yang sudah ada ke `http://<ip-server>:8091` (set `RANI_BIND_IP=0.0.0.0`).

---

## 2. Deploy di Portainer

### 2.1 Buat stack

1. Buka Portainer → **Stacks** → **Add stack**.
2. **Name**: `rani` (huruf kecil). Nama ini menjadi prefix container dan volume
   (`rani-api-1`, `rani_pgdata`, dst). **Jangan rename** setelah produksi.
3. **Build method**: **Web editor**.
4. Copy-paste seluruh isi `Portainer/docker-compose.yml` ke editor.

### 2.2 Isi environment variables

Di bagian **Environment variables**, pilih salah satu:

- Klik **Load variables from .env file**, upload `.env.portainer.example` yang
  sudah diisi, **atau**
- Tambahkan manual satu per satu (nama dan nilai).

Minimal yang **wajib** diisi (hanya dua):

| Variable | Cara mengisi |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -hex 16` — huruf/angka saja |
| `RANI_ADMIN_PASSWORD` | Password login admin pertama (kosong = acak, dicetak di log `api`) |

Variabel lain punya default aman dan **tidak perlu diisi**:

| Variable | Default | Keterangan |
|---|---|---|
| `RANI_DOMAIN` | kosong | Kosong = HTTP port 80 via IP. Isi hostname untuk HTTPS. |
| `RANI_INGEST_PEPPER` | otomatis | Diturunkan dari `POSTGRES_PASSWORD` saat container start. Isi manual hanya untuk override. |
| `RANI_REPORT_DB_PASSWORD` | otomatis | Diturunkan otomatis; menu Reports langsung aktif. |
| `RANI_ACME_EMAIL` | `admin@example.com` | Email Let's Encrypt (dipakai hanya kalau `RANI_DOMAIN` diisi). |
| `RANI_BIND_IP` | `127.0.0.1` | Port 8091 hanya dari server sendiri; akses publik lewat Caddy. |
| `TZ` | `Asia/Jakarta` | Zona waktu container. |
| `RANI_SCAN_SCHEDULER_TICK_S` | `30` | Tick loop penjadwal scan otomatis (detik). |
| `RANI_SCAN_SCHEDULE_MIN_INTERVAL_MIN` | `5` | Interval minimal mode loop (menit). |
| `RANI_SCHEDULE_TZ` | `Asia/Jakarta` | Zona waktu perhitungan jadwal. |

Catatan:

- `RANI_INGEST_PEPPER` mengunci enkripsi secret agent, community SNMP, dan bind
  password AD. Kalau dibiarkan kosong, nilainya **diturunkan dari
  `POSTGRES_PASSWORD`**. Artinya: **jangan ganti `POSTGRES_PASSWORD` setelah ada
  data**. Kalau perlu mengganti password DB, isi `RANI_INGEST_PEPPER` manual
  dengan nilai lama terlebih dahulu, baru ganti password.
- `RANI_ADMIN_PASSWORD` hanya dipakai saat tabel user masih kosong (boot pertama).
- Password DB dipakai di `DATABASE_URL`; gunakan huruf/angka. Kalau memakai
  karakter khusus, password harus URL-encoded.
- Jangan menambahkan `COMPOSE_PROJECT_NAME`; biarkan nama stack Portainer yang
  menentukan prefix volume.
- `RANI_HTTP_PORT` diisi angka saja (contoh `8091`). Jangan memakai format
  `127.0.0.1:8091` seperti pada compose lama; binding IP diatur oleh
  `RANI_BIND_IP`.

### 2.3 Deploy

Klik **Deploy the stack**. Urutan startup:

1. `db` dan `redis` start + healthcheck.
2. `api` menjalankan `alembic upgrade head`, membuat role report read-only,
   lalu uvicorn di port 8000.
3. `worker` mengonsumsi antrean ingest dari Redis.
4. `caddy` reverse proxy ke `api:8000` di port 80 (HTTP). Kalau `RANI_DOMAIN`
   diisi, Caddy sekaligus meminta sertifikat Let's Encrypt dan memakai HTTPS.

Penerbitan sertifikat pertama bisa memakan 30–60 detik (hanya saat `RANI_DOMAIN`
diisi).

### 2.4 Deploy di server baru (fresh install)

Cukup dari Portainer, tanpa clone repo dan tanpa build:

1. Siapkan server: Docker + Portainer; port **80** bebas (port 443 juga, kalau
   nanti mengaktifkan HTTPS).
2. Portainer → **Stacks → Add stack** → Name `rani` → **Web editor**.
3. Paste isi `Portainer/docker-compose.yml`.
4. **Environment variables** → **Load variables from .env file** → upload
   `.env.portainer.example` yang sudah diisi `POSTGRES_PASSWORD` dan
   `RANI_ADMIN_PASSWORD`.
5. Klik **Deploy the stack**.
6. Buka `http://<ip-server>/` lalu login.

Tidak ada langkah build dan tidak ada file yang perlu di-copy ke host. Semua data
berada di volume Docker (`rani_pgdata`, `rani_redisdata`, `rani_caddy_data`).

---

## 3. Verifikasi

```bash
# health API lewat Caddy (HTTP selama RANI_DOMAIN kosong)
curl -fsS http://<ip-server>/health
# {"status":"ok","db":true,"version":"0.2.0"}

# cek langsung dari server (port 8091 hanya di localhost)
curl -fsS http://127.0.0.1:8091/health
```

Buka `http://<ip-server>/` (atau `https://<RANI_DOMAIN>` kalau domain sudah
diisi), login dengan `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD`.

Kalau `RANI_ADMIN_PASSWORD` kosong, ambil password acak dari log:

```bash
docker logs rani-api-1 2>&1 | grep -i "password acak"
```

Cek status container:

```bash
docker ps --filter "name=rani-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

---

## 4. HTTPS / Caddy

**Default tanpa domain:** `RANI_DOMAIN` kosong → Caddy hanya melayani **HTTP di
port 80**, jadi aplikasi langsung bisa diakses lewat `http://<ip-server>/`.
Tidak ada sertifikat yang diminta.

**Mengaktifkan HTTPS nanti** (tanpa mengubah compose): isi `RANI_DOMAIN` (dan
opsional `RANI_ACME_EMAIL`) di Environment Variables Portainer → **Update the
stack**. Setelah itu Caddy otomatis:

- meminta & memperbarui sertifikat Let's Encrypt untuk `RANI_DOMAIN`,
- redirect HTTP → HTTPS,
- reverse proxy termasuk WebSocket realtime,
- menambahkan security header (HSTS, nosniff, X-Frame-Options, dll).

Yang perlu dipastikan **saat mengaktifkan HTTPS**:

1. `RANI_DOMAIN` hanya berisi hostname, contoh `rani.example.com` (tanpa `http://`).
2. DNS A/AAAA sudah propagasi: `dig +short rani.example.com`.
3. Port 80 dan 443 terbuka di firewall:
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```
4. Kalau memakai Cloudflare, gunakan mode **DNS only** (grey cloud) agar
   HTTP-01 challenge tidak terhalang. Untuk mode proxied, gunakan reverse proxy
   eksternal dengan sertifikat Cloudflare Origin.
5. Sertifikat disimpan di volume `rani_caddy_data`; jangan hapus volume ini
   agar tidak request ulang terus-menerus.

Mengganti domain:

1. Ubah `RANI_DOMAIN` di Environment Variables Portainer.
2. **Update the stack** (container Caddy akan dibuat ulang dengan Caddyfile baru).
3. Pastikan DNS domain baru sudah mengarah ke server.

---

## 5. Upgrade versi

1. Portainer → **Stacks** → `rani` → tab **Editor**.
2. Ubah `RANI_IMAGE` bila perlu (mis. dari `latest` ke `0.2.0`).
3. Centang **Re-pull image** (wajib kalau tetap memakai `latest`).
4. Klik **Update the stack**.

Migrasi database berjalan otomatis di container `api` (`alembic upgrade head`).
Data di volume `rani_pgdata` dan `rani_redisdata` tidak hilang.

Rollback: ubah `RANI_IMAGE` ke tag sebelumnya, lalu **Update the stack**.
Perhatikan bahwa migrasi DB umumnya tidak otomatis turun; restore backup bila perlu.

---

## 6. Backup & restore

### 6.1 Backup database (disarankan)

```bash
# cari nama container db
docker ps --format '{{.Names}}' | grep -E 'db'

# dump custom format (binary, aman untuk restore)
docker exec rani-db-1 pg_dump -U rani -d rani -Fc > rani-$(date +%F).dump
```

Simpan file dump di luar server.

### 6.2 Restore database

```bash
# 1) Lewat Portainer: stop service api & worker (atau seluruh stack)
# 2) Pastikan container db hidup
docker start rani-db-1

# 3) Restore
docker exec -i rani-db-1 pg_restore -U rani -d rani --clean --if-exists < rani-2026-11-20.dump

# 4) Start stack kembali dari Portainer
```

### 6.3 Backup volume (opsional)

```bash
docker run --rm \
  -v rani_pgdata:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/rani-pgdata-$(date +%F).tgz -C /data .
```

Volume yang dipakai:

| Volume | Isi |
|---|---|
| `rani_pgdata` | Data PostgreSQL |
| `rani_redisdata` | Antrean Redis (AOF) |
| `rani_caddy_data` | Sertifikat & state Caddy |
| `rani_caddy_config` | Konfigurasi runtime Caddy |

---

## 7. Konfigurasi penting

Semua variable lain sudah punya default aman. Yang paling sering diubah:

| Variable | Default | Keterangan |
|---|---|---|
| `RANI_IMAGE` | `adhityatp/raniassets:latest` | Pin ke `0.2.0` untuk produksi stabil |
| `RANI_DOMAIN` | kosong | Kosong = HTTP port 80 via IP; isi hostname untuk HTTPS |
| `RANI_ACME_EMAIL` | `admin@example.com` | Email Let's Encrypt (hanya saat domain diisi) |
| `RANI_BIND_IP` | `127.0.0.1` | `0.0.0.0` = buka 8091 ke LAN |
| `RANI_HTTP_PORT` | `8091` | Port host untuk API |
| `POSTGRES_PASSWORD` | — | **Wajib**, huruf/angka |
| `RANI_ADMIN_USER` | `admin` | Username admin awal |
| `RANI_ADMIN_PASSWORD` | kosong | Kosong = acak, dicetak di log |
| `RANI_INGEST_PEPPER` | otomatis | Diturunkan dari `POSTGRES_PASSWORD`; isi manual untuk override |
| `RANI_REPORT_DB_PASSWORD` | otomatis | Diturunkan otomatis; Reports aktif |
| `RANI_TOKENLESS_PUSH` | `1` | `0` = agent wajib enroll + HMAC |
| `RANI_OFFLINE_AFTER_S` | `10800` | Agent dianggap offline setelah 3 jam |
| `RANI_SCAN_*` | lihat file | Batas scan SNMP dan port map L2 |
| `RANI_SESSION_TTL_H` | `12` | Umur sesi login (jam) |

Daftar lengkap ada di `.env.portainer.example` dan `server/app/config.py`.

---

## 8. Keamanan

- Port 8091 default hanya bind ke `127.0.0.1`; akses publik lewat Caddy (port 80,
  atau 443 saat HTTPS aktif). Jangan set `RANI_BIND_IP=0.0.0.0` kecuali memang perlu.
- Ganti password admin setelah login pertama.
- Jangan mengganti `RANI_INGEST_PEPPER` setelah agent terdaftar. Kalau nilainya
  dibiarkan otomatis, ini berarti **jangan mengganti `POSTGRES_PASSWORD`** setelah
  ada data; untuk mengganti password DB, isi `RANI_INGEST_PEPPER` manual dengan
  nilai lama terlebih dahulu.
- Gunakan password DB huruf/angka, atau URL-encode karakter khusus.
- Untuk keamanan agent lebih ketat, setelah semua agent enroll set
  `RANI_TOKENLESS_PUSH=0` lalu update stack.
- Batasi akses Portainer itu sendiri; stack ini tidak mengatur keamanan Portainer.
- Backup `rani_pgdata` dan simpan `POSTGRES_PASSWORD` (sumber `RANI_INGEST_PEPPER`
  otomatis) di tempat aman.

---

## 9. Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| `required variable POSTGRES_PASSWORD is missing` | Isi `POSTGRES_PASSWORD` di Environment Variables. |
| Stack gagal deploy: `port 80/443 already allocated` | Port dipakai service lain. Hentikan proxy lama, atau hapus/nonaktifkan service `caddy` dan akses API langsung lewat `http://<ip-server>:8091` (set `RANI_BIND_IP=0.0.0.0`). |
| `http://<ip-server>/` tidak bisa dibuka | Cek container `caddy` hidup dan port 80 tidak dipakai service lain. Alternatif sementara: `http://<ip-server>:8091` dengan `RANI_BIND_IP=0.0.0.0`. |
| Caddy log: `obtain certificate: ...` | Hanya terjadi saat `RANI_DOMAIN` diisi. Cek DNS (`dig`), port 80 terbuka, dan domain tidak diproxy Cloudflare. Lihat `docker logs rani-caddy-1`. |
| `502 Bad Gateway` | API belum siap / migrasi gagal. Cek `docker logs rani-api-1` dan `curl http://127.0.0.1:8091/health`. |
| Dashboard tidak realtime | Pastikan akses lewat Caddy (bukan proxy tambahan yang buffering). Caddy sudah memakai `flush_interval -1`. |
| Menu Reports error | Cek `docker logs rani-api-1`. Role `rani_report` dibuat saat startup; jangan ganti `POSTGRES_USER` dari default `rani`. |
| Agent tidak bisa push | URL server harus reachable dari PC agent, firewall UDP/TCP sesuai, dan jam agent tidak skew > `RANI_TS_SKEW_S`. |
| Login gagal setelah restore DB | Password admin mengikuti data lama, bukan env baru. Gunakan password lama atau reset lewat DB. |
| Container exit `exec format error` | Host arm64. Image hanya amd64; pakai host amd64. |
| Stack aneh di Swarm | Gunakan endpoint Docker standalone. `depends_on` condition tidak didukung Swarm. |
| Volume terlihat baru setelah rename stack | Rename stack mengubah prefix volume. Kembalikan nama lama atau migrasikan volume. |

Perintah debugging:

```bash
docker logs -f rani-api-1
docker logs -f rani-worker-1
docker logs -f rani-caddy-1
docker logs -f rani-db-1
```

---

## 10. Uninstall

Lewat Portainer: **Stacks → rani → Delete**.

Container dan network akan terhapus, tetapi **volume tetap ada** (data aman).
Untuk menghapus data juga:

```bash
docker volume rm rani_pgdata rani_redisdata rani_caddy_data rani_caddy_config
```

---

## 11. Catatan versi image

Docker Hub `adhityatp/raniassets` saat ini memiliki:

| Tag | Build | Keterangan |
|---|---|---|
| `latest` | 22 Nov 2026 | Sama dengan `0.2.0` (jadwal scan otomatis per grup IP) |
| `0.2.0` | 22 Nov 2026 | Disarankan untuk produksi yang ingin pin versi |
| `0.1.0` | 16 Nov 2026 | Build sebelumnya, artefak agent sama |
| `v0.1.0` | 14 Nov 2026 | Build lebih lama, belum memuat artefak agent terbaru |

Untuk stack Portainer ini gunakan `latest` atau `0.2.0`.
