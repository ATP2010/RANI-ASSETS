# DEVGUIDE.md — RANI ProjectDev (doktrin untuk AI agent / dev baru)
> **Baca ini dulu sebelum menyentuh kode apa pun.** Dokumen ini = konteks, aturan, dan konvensi proyek.
> (Catatan: file ini sengaja tidak bernama AGENTS.md karena nama itu dilindungi tooling; semua agent AI harus memperlakukan file ini sebagai setara.)

## 1. Apa aplikasi ini
**RANI** = IT asset management / cyber-asset inventory mirip **Lansweeper**, self-hosted, target ±1.000 endpoint Windows + perangkat jaringan.
Loop inti: **`raniPush`** (agent di PC user, CLI `raniPush <targetIP>`, jalan via Windows Task Scheduler) → **server FastAPI menangkap** (`POST /api/v1/ingest/push`) → **data tampil detail di web dashboard** (AdminLTE 4 + Apache ECharts + WebSocket realtime).
Sumber requirements: `/root/RaniProject/baseOn/analysis results.md` (§3 blueprint, §4b SNMP, §5 keputusan owner signed-off 2026-11-13).

## 2. Stack & keputusan tetap (JANGAN diganti tanpa owner sign-off)
| Layer | Pilihan | Alasan |
|---|---|---|
| Agent | Python 3 stdlib-first, PyInstaller exe | tim Python; Get-CimInstance via subprocess untuk WMI |
| Server | FastAPI + gunicorn + Jinja2 + htmx | reuse skill/fondasi `/root/rani` |
| DB | **PostgreSQL 16** (JSONB) | payload agent & MIB fleksibel; MariaDB live dipakai report lain saja |
| Queue/cache | Redis 7 (`noeviction`) | stream ingest + WS pub/sub |
| UI | AdminLTE 4 (Bootstrap 5) + Apache ECharts 5.5 (vendored) + WebSocket | owner request |
| Deploy | docker compose, image push → registry lokal `192.168.88.92:5000` | migrasi = pull + `up -d` |
| Timezone | **Asia/Jakarta (WIB)** semua container (`TZ=`) | owner request |
| SNMP | **Klien stdlib sendiri** (`server/app/snmp.py`: BER + GET/GETNEXT). Alasan: kebutuhan hanya GET/GETNEXT, image tanpa dependency tambahan, dan mudah diuji dengan fake agent UDP. `pysnmp-lextudio` tetap opsi bila butuh v3/trap | implementasi Nov 2026 |
| Ingest auth | HMAC-SHA256(agent_secret, ts+nonce+body) + nonce replay-guard; **tanpa TLS wajib** (LAN by-IP) | owner: target manual IP, Task Scheduler cmd |

## 3. Struktur repo
```
ProjectDev/
├── DEVGUIDE.md          ← kamu di sini (doktrin agent)
├── CHECKLIST.md         ← source-of-truth progres, WAJIB di-update tiap task selesai
├── README.md            ← cara run
├── docker-compose.yml   ← api, worker, postgres, redis (registry: 192.168.88.92:5000/rani-*)
├── schema/
│   └── agent_payload_v1.json   ← kontrak JSON payload raniPush (versioned!)
├── agent/               ← raniPush (Windows collector + pusher)
├── server/
│   ├── app/             ← FastAPI (main, api/ingest, api/assets, ws, templates/, static/)
│   └── worker/          ← ingest worker + SNMP scanner (raniScan) + reconciler
├── db/                  ← alembic migrations
└── scripts/             ← build exe, push image ke registry, seed
```

## 4. Aturan teknis
1. **Payload versioned**: field `schema_version` integer. Perubahan kontrak = tambah file schema versi baru, server tetap terima versi lama. Jangan pernah breaking-change v1.
2. **Identity asset** (reconciler, urut): `machine_id` → `serial` → `primary_mac` → `hostname`. **IP bukan kunci identitas** (hanya atribut). Sumber: pola Lansweeper §1.3.
3. **Software = delta model**, bukan snapshot-per-run: `software(asset_id,...,present,first_seen,last_seen)` + `software_events(install/uninstall/change)`. Raw payload dibuang >90 hari.
4. **SNMP**: probe pertama wajib `sysObjectID 1.3.6.1.2.1.1.2.0` (timeout 1s ×1 retry → tandai `timeout`). Community read-only, terenkripsi at-rest per grup (`scan_groups.community_enc`). Hasil mentah (sysDescr + custom OID) disimpan di `scan_results.oid_values` dan `assets.attrs.snmp` supaya device-type baru bisa di-re-match tanpa re-scan. Jangan pernah kirim SNMP SET.
5. **Idempotent ingest**: 2 push identik (sha body sama, <1 interval) → ACK tanpa insert duplikat.
6. **Secrets**: agent secret di-hash (bcrypt/sha256+pepper); credential SNMP terenkripsi at-rest; `.env` gitignored.
7. **WebSocket event names**: `asset.new`, `asset.update`, `asset.offline`, `scan.progress`, `scan.done`. Payload kecil (id + ringkasan); UI fetch detail via REST.
8. **Task scheduler contract**: `raniPush 192.168.88.92` exit code 0/1 saja (0=berhasil/terspool, 1=gagal fatal), tidak interaktif, tidak butuh admin untuk field utama (fallback null, jangan crash).
9. **Git**: Conventional Commits (`feat:`, `fix:`, `docs:`), commit per milestone CHECKLIST.
10. **Bukti dulu baru centang**: curl output / docker logs / query DB = bukti. Jangan klaim done tanpa verifikasi hasil di sistem nyata.
11. **Report SQL = read-only**: query custom user hanya lewat role `rani_report` (SELECT + `default_transaction_read_only`), dibungkus `LIMIT`, dengan statement timeout. Jangan pernah menjalankan report SQL memakai koneksi aplikasi (`rani`) — itu membuka DDL/DML ke user. Tabel kredensial (`app_users`, `auth_sessions`, `enrollment_tokens`) tetap di-revoke.

## 5. Cara run dev
```bash
cd /root/RaniProject/ProjectDev
cp .env.example .env          # isi POSTGRES_PASSWORD, RANI_INGEST_PEPPER, RANI_ADMIN_PASSWORD
docker compose up -d --build  # api :8091, UI http://192.168.88.92:8091  (project: rani-inv)
# agent dev test (tanpa exe, tanpa token):
python agent/raniPush.py --collect > payload.json
python agent/raniPush.py 192.168.88.92:8091          # push langsung, agent auto-terdaftar
# opsional/legacy (hanya bila RANI_TOKENLESS_PUSH=0):
python agent/raniPush.py --enroll <token> 192.168.88.92:8091
python agent/raniPush.py 192.168.88.92:8091
# build exe Windows (Wine + Python Windows sudah terpasang di mesin ini):
bash scripts/build-exe.sh      # hasil: release/raniPush.exe
# verifikasi:
docker exec rani-inv-api-1 sh -c "cd /srv && python -m unittest discover -s tests -v"
python3 scripts/smoke_test.py --base http://127.0.0.1:8091
```

**PENTING — jangan bentrok dengan stack lama:** repo `/root/rani` sudah memakai compose
project `rani` (port 8088/8443, image `rani-api`). ProjectDev memakai project name
`rani-inv` dan image `rani-server`; jangan pernah menjalankan `docker compose down`
di direktori lain atau mengubah project name ProjectDev menjadi `rani`.

## 6. Keputusan arsitektur tercatat (ADR-mini)
- **ADR-D1**: push-model dulu, agentless scan menyusul → memangkas kebutuhan kredensial domain/WMI remote; SNMP tetap agentless-pull.
- **ADR-D2**: HTTP by-IP + HMAC (bukan TLS) untuk LAN; TLS opsional via nginx nanti — jangan blok desain karena ini.
- **ADR-D3**: UI server-rendered (Jinja2+htmx) bukan SPA → 1 container, tanpa node build stage.
- **ADR-D4**: satu service `worker` menjalankan ingest-consumer + scanner scheduler; pecah lagi kalau tercekik.

## 7. Keputusan implementasi yang sudah dikunci (jangan re-derive)

- **Verifikasi HMAC**: server menyimpan `agent_secret` terenkripsi Fernet (key = HKDF dari
  `RANI_INGEST_PEPPER`), karena HMAC butuh key yang bisa dibaca server. Bukan bcrypt —
  bcrypt tidak bisa diverifikasi HMAC-nya. Berganti pepper = semua agent harus enroll ulang.
- **Urutan ingest**: API commit row `software_reports` DULU, baru `XADD`; worker punya
  `requeue_loop` yang meng-enqueue ulang report `queued` > 2 menit (self-healing kalau
  Redis sempat mati).
- **Identitas**: kalau kandidat match lewat serial/MAC/hostname tapi `machine_id` berbeda,
  JANGAN merge — buat asset baru (cegah merge PC re-image / snapshot VM / payload uji).
- **Software drop guard**: bila incoming < 50% dari yang tercatat dan existing > 10,
  uninstall massal dilewati + alasan ditulis ke `software_reports.error`.
- **Worker** = ingest consumer + requeue sweeper + stale sweep (interval 5 menit,
  `RANI_OFFLINE_AFTER_S` default 3 jam), sesuai ADR-D4.
- **UI**: template AdminLTE 4 di `server/app/static/vendor/` (vendored, tanpa CDN/build step);
  WS `/ws` auth lewat cookie sesi, event via Redis pub/sub channel `rani:events`.
- **Test**: `server/tests/` = unit murni (stdlib `unittest`, tanpa DB) dijalankan di dalam
  image; `scripts/smoke_test.py` = end-to-end lewat CLI agent asli.

## 8. Kontak konteks
- Analisis Lansweeper + blueprint: `../baseOn/analysis results.md`
- Repo REA (reverse-engineer toolkit; referensi discipline kontrak JSON-schema): `..`
- Fondasi RANI lama (pattern RBAC/FastAPI yang boleh di-reuse sebagai referensi baca-saja): `/root/rani` — **jangan tulis kode aplikasi ke sana**, ProjectDev ini rumah baru.
