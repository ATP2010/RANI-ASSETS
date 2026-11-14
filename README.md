# RANI ProjectDev

IT asset inventory self-hosted (mirip Lansweeper): **raniPush** agent → FastAPI ingest →
dashboard AdminLTE realtime (WebSocket).

- Requirements & analisis: [`../baseOn/analysis results.md`](../baseOn/analysis%20results.md)
- Doktrin untuk AI agent/dev: [`DEVGUIDE.md`](DEVGUIDE.md) ← **baca dulu**
- Progres: [`CHECKLIST.md`](CHECKLIST.md)
- UI: dashboard memakai **Apache ECharts 5.5** (vendored di `server/app/static/vendor/echarts.min.js`,
  tanpa CDN/online) dan sidebar AdminLTE `sidebar-mini` — status collapse disimpan di
  `localStorage` (`lte.sidebar.state`) sehingga tetap ringkas saat pindah menu.
- Ikon aplikasi: `server/app/static/img/` (`favicon.ico`, `icon-32/192/512.png`,
  `apple-touch-icon.png`) + `static/manifest.json`; logo sidebar memakai `icon.png` dan
  versi kecil `icon-32.png` saat sidebar ringkas. Ganti logo = jalankan
  `python3 scripts/make-icons.py <logo.png>` lalu rebuild image — langkah lengkap di
  [`docs/branding.md`](docs/branding.md).

## Status sekarang

| Bagian | Status |
|---|---|
| Server ingest + reconciler + UI (F1) | jalan, terverifikasi end-to-end |
| Agent `raniPush` Linux | jalan, terverifikasi (payload nyata → asset) |
| Agent `raniPush` Windows (WMI/registry/PowerShell) | kode ada, **belum diuji di PC Windows nyata** |
| SNMP scanning (F2), installer exe + GNS (F3) | belum |

## Quick start (dev LXC 192.168.88.92)

```bash
cd ProjectDev
cp .env.example .env      # isi POSTGRES_PASSWORD, RANI_ADMIN_PASSWORD, RANI_INGEST_PEPPER
docker compose up -d --build
```

- UI: `http://192.168.88.92:8091` — login `RANI_ADMIN_USER` / `RANI_ADMIN_PASSWORD`
  dari `.env` (dibuat otomatis saat boot pertama).
- Compose project name = **`rani-inv`** (container `rani-inv-api-1`, dst.) supaya tidak
  bentrok dengan stack lama `/root/rani` (project `rani`, port 8088/8443).
- API docs (mode dev): `http://192.168.88.92:8091/api/docs`

## Alur pakai

1. Login → menu **Agents** → panel **Download agent (Windows)** → unduh
   `raniPush-signed.exe` (dan `rani-push-signing.cer` + `install-cert.ps1` bila PC
   memblokir "unknown publisher"). Tidak ada token/enroll untuk agent 0.2+.
2. Di PC target (Windows, PowerShell **as Administrator**):
   ```
   .\install-agent.ps1 -Server 192.168.88.92:8091 -ExePath .\raniPush-signed.exe
   ```
   Script menyalin exe ke `C:\Rani`, mendaftarkan Task Scheduler tiap 60 menit, lalu
   push pertama. Manual:
   ```
   raniPush-signed.exe 192.168.88.92:8091                # collect + push (exit 0)
   schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f `
     /tr "C:\Rani\raniPush-signed.exe 192.168.88.92:8091"
   ```
   Server mengenali PC dari `machine_id` (MachineGuid) dan mendaftarkan agent pada push
   pertama; revoke agent kapan saja di UI Agents. Ingin wajib kredensial? Set
   `RANI_TOKENLESS_PUSH=0` di `.env` lalu pakai token + HMAC (`--enroll`).
   Panduan lengkap Windows (Task Scheduler, SmartScreen/SAC, troubleshooting, uninstall):
   [`docs/agent-windows.md`](docs/agent-windows.md).
3. Push masuk → API validasi (digest + nonce + timestamp + skema; HMAC bila agent
   ter-enroll) → Redis Stream → worker merekonsiliasi → halaman **Assets** dan dashboard
   ter-update via WebSocket.

Push gagal (server mati/jaringan) → payload di-spool dan dicoba lagi pada run berikutnya
(maks 7 hari).

## Build agent Windows (`raniPush.exe`)

Artefak di `release/` (tidak di-commit, binary):

| File | Isi | Kapan dipakai |
|---|---|---|
| `raniPush.exe` | exe unsigned, 7,4 MB | PC yang tidak memblokir exe |
| `raniPush-signed.exe` | exe + signature internal + timestamp | PC dengan SmartScreen/"unknown publisher"; pasang `rani-push-signing.cer` dulu |
| `rani-push-signing.cer` | sertifikat publik code-signing internal | dipasang via `scripts/install-cert.ps1` |
| `raniPush-portable.zip` | Python embeddable resmi + `raniPush.py` + `raniPush.cmd` | PC dengan Smart App Control/AV ketat yang memblokir exe buatan sendiri |

Keempat file itu bisa diunduh langsung dari browser di `http://192.168.88.92:8091/agents`
(route `/downloads/<nama>`, wajib login; compose me-mount `release/` dan `scripts/`
read-only ke container).

```bash
bash scripts/build-exe.sh        # → release/raniPush.exe
bash scripts/sign-exe.sh         # → release/raniPush-signed.exe + .cer
bash scripts/build-portable.sh   # → release/raniPush-portable.zip

# di Windows (paling andal, atau lewat GitHub Actions workflow build-agent-exe):
python -m pip install pyinstaller==6.11.1
pyinstaller --noconfirm --clean --distpath release agent/raniPush.spec
```

Kalau Windows memblokir exe: lihat
[`docs/agent-windows.md` §10](docs/agent-windows.md#10-kalau-windows-memblokir-ranipushexe-smartscreen--smart-app-control).

## Verifikasi

```bash
# unit test aturan identitas/normalisasi/kontrak payload (di dalam image)
docker exec rani-inv-api-1 sh -c "cd /srv && python -m unittest discover -s tests -v"

# smoke test end-to-end (login → token → enroll → push → reconcile → UI/CSV)
python3 scripts/smoke_test.py --base http://127.0.0.1:8091
```

## Deploy ke server lain (migrasi)

```bash
bash scripts/push-registry.sh                 # build + push 192.168.88.92:5000/rani-server:latest
# di server baru:
git clone <repo> && cd ProjectDev
cp .env.example .env && $EDITOR .env          # pepper HARUS sama bila DB yang sama dibawa
RANI_IMAGE=192.168.88.92:5000/rani-server:latest docker compose pull
RANI_IMAGE=192.168.88.92:5000/rani-server:latest docker compose up -d
```

Compose sengaja portable: tanpa `network_mode: host`, tanpa IP hardcode, hanya `TZ=Asia/Jakarta`.

## Struktur

```
ProjectDev/
├── docker-compose.yml      api, worker, postgres 16.4, redis 7.4 (project rani-inv)
├── schema/agent_payload_v1.json   kontrak payload agent (versioned)
├── agent/raniPush.py       collector+pusher Windows/Linux (stdlib, tanpa dependensi)
├── server/app/             FastAPI: api/, ingest/ (reconciler), templates/, static/
├── server/worker/          konsumen Redis Stream + requeue + stale sweep
├── db/                     alembic (0001_initial = schema rani_inventory)
├── server/tests/           unit test murni
└── scripts/                push-registry.sh, smoke_test.py
```

## Keamanan singkat

- Agent auth: `HMAC-SHA256(agent_secret, timestamp+nonce+body)` + `sha256(body)` digest,
  toleransi skew 300s, nonce anti-replay di Redis. Secret disimpan terenkripsi (Fernet,
  key turunan `RANI_INGEST_PEPPER`) — bukan plaintext.
- Tidak ada TLS wajib (LAN by-IP, keputusan owner ADR-D2); HMAC tetap jalan tanpa TLS.
- UI: session cookie HttpOnly + bcrypt + RBAC (`admin` > `operator` > `reader`), audit log.
- `.env` gitignored — jangan pernah commit password/pepper.