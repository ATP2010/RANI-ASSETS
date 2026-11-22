# RANI — Dokumentasi Lengkap (consolidated)

## Lokasi repo (live)
- **GitHub (source code)**: https://github.com/ATP2010/RANI-ASSETS (branch `main`, HEAD `7fd601b`)
  - Clone: `git clone https://github.com/ATP2010/RANI-ASSETS.git`
  - Raw file: `https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/<path>`
- **Docker Hub (image)**: https://hub.docker.com/repository/docker/adhityatp/raniassets
  - Tag: `adhityatp/raniassets:0.1.0` (digest `sha256:081a272f91e8...`) + `:latest`
  - Pull: `docker pull adhityatp/raniassets:0.1.0`
  - Size: ±426 MB (121 MB compressed)
- **Status push**: GitHub ✅, Docker Hub ✅ (2026-11-16)


> Dokumen ini menggabungkan (dan menduplikasi-semantik) isi dari:
> - [`analysis.md`](analysis.md) (requirements & analisis awal)
> - [`../CHECKLIST.md`](../CHECKLIST.md) (source-of-truth progres)
> - [`../DEVGUIDE.md`](../DEVGUIDE.md) (doktrin dev/agent)
> - [`deploy-dockerhub.md`](deploy-dockerhub.md) + [`deploy-caddy.md`](deploy-caddy.md) (setup, deploy, CI, credential, trust)
>
> Salinan "live" tetap ada di `CHECKLIST.md` dan `DEVGUIDE.md` di root repo
> (dibutuhkan agent yang berjalan di folder ProjectDev). Dokumen ini adalah
> snapshot terkonsolidasi; folder `baseOn/` sudah dihapus dan isinya dimerge ke `docs/`.

---

## 1. Apa aplikasi ini

**RANI** = IT asset management / cyber-asset inventory mirip **Lansweeper**, self-hosted,
target ±1.000 endpoint Windows + perangkat jaringan.

Loop inti: **`raniPush`** (agent di PC user, CLI `raniPush <targetIP>`, jalan via Windows
Task Scheduler) → **server FastAPI menangkap** (`POST /api/v1/ingest/push`) → **data tampil
detail di web dashboard** (AdminLTE 4 + Apache ECharts + WebSocket realtime).

Sumber requirements: `docs/analysis.md` (§3 blueprint, §4b SNMP, §5 keputusan
owner signed-off 2026-11-13).

---

## 2. Requirements & fitur (ringkasan dari analysis results)

Fitur utama (lihat detail di `analysis results.md`):
- **F0** Spike raniPush (Windows collector): identity, hardware, OS, network, software,
  security, users, JSON schema v1, push+HMAC+retry/spool.
- **F1** Server ingest + reconciler + UI dasar: docker compose, Alembic, enroll, ingest,
  worker, asset list/detail, login/RBAC/audit, WS realtime, custom reports SQL.
- **F2** SNMP network scan (raniScan) + dashboard: klien SNMP stdlib, v1/v2c, custom OID,
  bridge FDB port map, IP range target, scan on-demand + progress WS, dashboard ECharts.
- **F3** Ops & distribusi: build exe, enrollment, retention, CSV export, push image
  registry/Docker Hub, backup.
- **F4** Backlog nilai tambah: Linux collector, vulnerability insights, lifecycle/EOL,
  webhooks/GraphQL/MCP, discovery pasif, software normalization, Actions (Lansweeper-style),
  Reports datatable, Dashboard custom widgets.
- **F5** Users & access: login lokal + AD, role/permission custom, sync group AD,
  sesi & audit. (F5.1–F5.7 selesai; F5.8 MFA/SSO lanjutan.)

Fitur yang sudah selesai (ringkas): F0 (sebagian), F1 (lengkap), F2 (sebagian —
printer enrichment & jadwal scan belum), F3 (sebagian), F4 (Actions, Reports datatable,
Dashboard custom, software normalization), F5 (F5.1–F5.7).

---

## 3. Stack & keputusan tetap

| Layer | Pilihan | Alasan |
|---|---|---|
| Agent | Python 3 stdlib-first, PyInstaller exe | tim Python; WMI via subprocess |
| Server | FastAPI + gunicorn + Jinja2 + htmx | reuse fondasi `/root/rani` |
| DB | PostgreSQL 16 (JSONB) | payload & MIB fleksibel |
| Queue/cache | Redis 7 (`noeviction`) | stream ingest + WS pub/sub |
| UI | AdminLTE 4 (Bootstrap 5) + ECharts 5.5 (vendored) + WebSocket | owner request |
| Deploy | docker compose, image push → registry lokal/Docker Hub | migrasi = pull + `up -d` |
| Timezone | Asia/Jakarta (WIB) semua container (`TZ=`) | owner request |
| SNMP | Klien stdlib sendiri (BER + GET/GETNEXT), tanpa dependency baru | hanya GET/GETNEXT, mudah diuji |
| Ingest auth | HMAC-SHA256 + nonce replay-guard; tanpa TLS wajib (LAN by-IP) | target manual IP |

**ADR-mini:**
- ADR-D1: push-model dulu, agentless scan menyusul.
- ADR-D2: HTTP by-IP + HMAC (bukan TLS) untuk LAN; TLS opsional via reverse proxy.
- ADR-D3: UI server-rendered (Jinja2+htmx) bukan SPA.
- ADR-D4: satu service `worker` (ingest + scanner scheduler); pecah kalau tercekik.

---

## 4. Struktur repo

```
ProjectDev/
├── DEVGUIDE.md / CHECKLIST.md / README.md
├── docker-compose.yml          (dev: api, worker, postgres, redis)
├── docker-compose.hub.yml      (prod: pull image dari Docker Hub)
├── docker-compose.caddy.yml    (overlay Caddy/HTTPS)
├── Caddyfile
├── .env.example / .env.hub.example / .env.secrets
├── schema/agent_payload_v1.json
├── agent/                      (raniPush collector)
├── server/                     (FastAPI app + worker)
├── db/                         (Alembic migrations 0001–0012)
├── scripts/                    (build, push, install, sign)
├── docs/                       (deploy, scan, users, actions, reports, branding)
└── .github/workflows/          (build-agent-exe, push-dockerhub)
```

---

## 5. Aturan teknis (ringkas)

1. Payload versioned (`schema_version` integer). Perubahan kontrak = file schema baru, server tetap terima versi lama.
2. Identity asset (reconciler): `machine_id` → `serial` → `primary_mac` → `hostname`. IP bukan kunci.
3. Software = delta model (`present` + events), bukan snapshot-per-run.
4. SNMP: probe sysObjectID dulu; community terenkripsi at-rest; hasil mentah di `scan_results.oid_values` & `assets.attrs.snmp`; FDB tidak membuat asset baru; MAC hilang = `present=false`.
5. Idempotent ingest: 2 push identik (sha sama, <1 interval) → ACK tanpa duplikat.
6. Secrets: agent secret di-hash; SNMP credential terenkripsi; `.env` gitignored.
7. WS event names: `asset.new`, `asset.update`, `asset.offline`, `scan.progress`, `scan.done`.
8. Task scheduler contract: exit code 0/1 saja, tidak interaktif.
9. Git: Conventional Commits, commit per milestone.
10. Bukti dulu baru centang (curl/log/query DB).
11. Report SQL = read-only via role `rani_report` (`default_transaction_read_only`, LIMIT, statement timeout).
12. Actions dieksekusi di PC pengguna (native host + ekstensi Chromium), bukan di server.
13. Akun login ≠ user asset: username polos = lokal (bcrypt); `DOMAIN\user`/UPN = AD. Permission = union semua role; admin terkunci. Bind password AD terenkripsi (Fernet + pepper), write-only, tidak ada tulis ke AD.

---

## 6. Progress checklist (ringkas)

Status lengkap di `ProjectDev/CHECKLIST.md`. Ringkasan:

- **F0** (raniPush spike): sebagian selesai (F0.1, F0.4, F0.5, F0.7, F0.8, F0.9, F0.10 done; F0.2, F0.3, F0.6 in-progress).
- **F1** (server ingest + UI dasar): selesai semua (F1.1–F1.12).
- **F2** (SNMP scan + dashboard): sebagian (F2.1–F2.7, F2.4b, F2.5 done; F2.8 printer enrichment belum; jadwal scan belum).
- **F3** (ops & distribusi): sebagian (build exe, enrollment, CSV, push registry, Docker Hub, download agent, Actions script, Dashboard custom, Reports datatable, Port map done; retention/backup/remote config belum).
- **F4** (backlog): sebagian (Actions, Reports datatable, Dashboard custom, software normalization done; vulnerability insights, lifecycle, webhooks/GraphQL/MCP, discovery pasif, license/SAM belum).
- **F5** (Users & access): F5.1–F5.7 selesai; F5.8 (MFA & SSO) lanjutan.

Riwayat pekerjaan sesi (12+ item) tercatat di `CHECKLIST.md` dengan bukti per task.

---

## 7. Cara run dev

```bash
cd /root/RaniProject/ProjectDev
cp .env.example .env          # isi POSTGRES_PASSWORD, RANI_INGEST_PEPPER, RANI_ADMIN_PASSWORD
docker compose up -d --build  # api :8091, UI http://192.168.88.92:8091 (project: rani-inv)
# agent dev test:
python agent/raniPush.py --collect > payload.json
python agent/raniPush.py 192.168.88.92:8091
# verifikasi:
docker exec rani-inv-api-1 sh -c "cd /srv && python -m unittest discover -s tests -v"
python3 scripts/smoke_test.py --base http://127.0.0.1:8091
```

PENTING: jangan bentrok dengan stack lama `/root/rani` (project `rani`, port 8088/8443).

---

## 8. Deploy & CI

Lihat `docs/deploy-dockerhub.md` (atau `docs/deploy-caddy.md`) untuk panduan lengkap. Ringkasan:

### Deploy Docker Hub (pull & run)
- Image: `adhityatp/raniassets:0.1.0` (+ `:latest`), repo public, ±426 MB.
- GitHub: https://github.com/ATP2010/RANI-ASSETS
- Docker Hub: https://hub.docker.com/repository/docker/adhityatp/raniassets
- Image berisi API+worker+skema+migrasi+docs+skrip+artefak agent.
- Yang tetap di host: `docker-compose.hub.yml` + `.env`, volume Postgres/Redis.
- Panduan: `docs/deploy-dockerhub.md`.

**Deploy di new server (satu perintah):**
```bash
sudo bash scripts/install-ubuntu.sh
# atau: curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/scripts/install-ubuntu.sh | sudo bash
```

**Deploy manual:**
```bash
mkdir -p /opt/rani && cd /opt/rani
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/docker-compose.hub.yml -o docker-compose.hub.yml
curl -fsSL https://raw.githubusercontent.com/ATP2010/RANI-ASSETS/main/.env.hub.example -o .env.hub.example
cp .env.hub.example .env   # edit: RANI_DOMAIN, RANI_ACME_EMAIL, password, pepper
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d
```

- Image: `adhityatp/raniassets:v0.1.0` (+ `:latest`), repo public, ±386 MB.
- Image berisi API+worker+skema+migrasi+docs+skrip+artefak agent.
- Yang tetap di host: `docker-compose.hub.yml` + `.env`, volume Postgres/Redis.
- Panduan: `docs/deploy-dockerhub.md`.

### Deploy dengan Caddy (HTTPS)
- Overlay: `docker-compose.caddy.yml` + `Caddyfile`.
- Installer satu perintah: `scripts/install-ubuntu.sh`.
- Panduan: `docs/deploy-caddy.md`.

### CI/CD (GitHub Actions)
- `build-agent-exe.yml`: build raniPush.exe di runner Windows (trigger push tag `agent-v*`).
- `push-dockerhub.yml`: build & push image (trigger push main/tag v*/manual).
- Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

### Push manual
```bash
bash scripts/build-exe.sh && bash scripts/sign-all.sh && bash scripts/build-portable.sh
bash scripts/push-dockerhub.sh 0.2.0
```

### Push ke GitHub
```bash
git config --global user.name "Nama"
git config --global user.email "email@anda.com"
git remote add origin https://github.com/<user>/<repo>.git
git branch -M main
git push -u origin main
```

### Upgrade di server baru
```bash
cd /opt/rani
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml pull
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d
```

---

## 9. Trust Windows (exe tidak diblokir)

Realitas: tidak ada cara gratis untuk trust otomatis di PC tak terkelola.
SmartScreen butuh signature + reputasi (OV/EV cert berbayar).

### Strategi gratis (sudah diimplementasikan)
1. `install-agent.ps1` — `Unblock-File` otomatis.
2. `build-host.sh` — sign `rani-action-host.exe` (self-signed).
3. `scripts/sign-all.sh` — sign massal.
4. `agents_push.html` — tip portable (Jalur A) sebagai rekomendasi.
5. `docs/agent-windows.md` — dokumentasi Solusi A-D.

### Distribusi via GPO (PC terkelola)
```
GPO (AD)
  ├─ copy raniPush-signed.exe + rani-push-signing.cer → C:\Rani\
  ├─ import .cer ke Trusted Root + Trusted Publishers
  └─ buat Scheduled Task: C:\Rani\raniPush.exe <server-ip> tiap 60 menit
```

### Diagnosa jika masih diblokir
1. `Get-AuthenticodeSignature` → harus `Valid`
2. Cek cert di store `Root` dan `TrustedPublisher` (keduanya 1)
3. SAC mode enforce → pakai portable (Jalur A)
4. ASR rule aktif → minta IT allowlist publisher
5. Zone.Identifier → `Unblock-File` + restart
6. TimeStamperCertificate kosong → re-sign dengan timestamp publik

### Artefak distribusi (`release/`)
- `raniPush.exe` (unsigned) — jangan distribusikan
- `raniPush-signed.exe` (signed + timestamp) — distribusikan ini
- `rani-action-host.exe` (unsigned)
- `rani-action-host-signed.exe` (signed)
- `rani-push-signing.cer` (publik)
- `raniPush-portable.zip` (Jalur A, lolos SmartScreen)

---

## 10. Lokasi file penting

| Kategori | File |
|---|---|
| CI/CD | `.github/workflows/build-agent-exe.yml`, `.github/workflows/push-dockerhub.yml` |
| Deploy compose | `docker-compose.yml`, `docker-compose.hub.yml`, `docker-compose.caddy.yml` |
| Config env | `.env.example`, `.env.hub.example`, `.env.secrets` (gitignored) |
| Caddy | `Caddyfile`, `docs/deploy-caddy.md` |
| Installer | `scripts/install-ubuntu.sh` |
| Push image | `scripts/push-dockerhub.sh`, `scripts/push-registry.sh` |
| Build agent | `scripts/build-exe.sh`, `scripts/build-host.sh`, `scripts/build-portable.sh` |
| Sign | `scripts/sign-exe.sh`, `scripts/sign-all.sh` |
| Windows install | `scripts/install-agent.ps1`, `scripts/install-cert.ps1` |
| Docs | `docs/deploy-dockerhub.md`, `docs/deploy-caddy.md`, `docs/agent-windows.md`, `docs/reports.md`, `docs/scan.md`, `docs/users.md`, `docs/actions.md` |
| Migrations | `db/versions/0001..0012` (idempotent untuk fresh install) |

---

## 11. Catatan penting

- **Pepper (`RANI_INGEST_PEPPER`)** harus sama antar server bila DB dibawa. Jangan generate ulang.
- **Migrasi DB** otomatis via `alembic upgrade head` di entrypoint api. Sudah idempotent (0005/0006 fix) untuk fresh install.
- **`.env` dan `release/`** gitignored — jangan commit.
- **Image public** (`adhityatp/raniassets`) → new server cukup `docker pull`, tidak perlu clone repo.
- **File project** (compose, Caddyfile, .env) tetap harus ada di host — Docker Hub hanya menyimpan image.
- **Sertifikat code-signing** berlaku 3 tahun (1095 hari). Set reminder re-sign sebelum kadaluarsa.
- **Trust otomatis di PC tak terkelola** butuh OV/EV cert berbayar. Gratis hanya portable + Unblock + self-sign (PC terkelola).

---

## 12. Kontak konteks

- Analisis Lansweeper + blueprint: `docs/analysis.md`
- Repo REA (reverse-engineer toolkit; referensi discipline kontrak JSON-schema): sudah tidak ada di `/root/RaniProject` (dulu `baseOn/`)
- Fondasi RANI lama (pattern RBAC/FastAPI yang boleh di-reuse sebagai referensi baca-saja): `/root/rani` — jangan tulis kode aplikasi ke sana.
- Dokumentasi live: `ProjectDev/CHECKLIST.md` (progres), `ProjectDev/DEVGUIDE.md` (doktrin dev/agent).
