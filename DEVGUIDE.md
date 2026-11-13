# DEVGUIDE.md — RANI ProjectDev (doktrin untuk AI agent / dev baru)
> **Baca ini dulu sebelum menyentuh kode apa pun.** Dokumen ini = konteks, aturan, dan konvensi proyek.
> (Catatan: file ini sengaja tidak bernama AGENTS.md karena nama itu dilindungi tooling; semua agent AI harus memperlakukan file ini sebagai setara.)

## 1. Apa aplikasi ini
**RANI** = IT asset management / cyber-asset inventory mirip **Lansweeper**, self-hosted, target ±1.000 endpoint Windows + perangkat jaringan.
Loop inti: **`raniPush`** (agent di PC user, CLI `raniPush <targetIP>`, jalan via Windows Task Scheduler) → **server FastAPI menangkap** (`POST /api/v1/ingest/push`) → **data tampil detail di web dashboard** (AdminLTE 4 + Chart.js + WebSocket realtime).
Sumber requirements: `/root/RaniProject/baseOn/analysis results.md` (§3 blueprint, §4b SNMP, §5 keputusan owner signed-off 2026-11-13).

## 2. Stack & keputusan tetap (JANGAN diganti tanpa owner sign-off)
| Layer | Pilihan | Alasan |
|---|---|---|
| Agent | Python 3 stdlib-first, PyInstaller exe | tim Python; Get-CimInstance via subprocess untuk WMI |
| Server | FastAPI + gunicorn + Jinja2 + htmx | reuse skill/fondasi `/root/rani` |
| DB | **PostgreSQL 16** (JSONB) | payload agent & MIB fleksibel; MariaDB live dipakai report lain saja |
| Queue/cache | Redis 7 (`noeviction`) | stream ingest + WS pub/sub |
| UI | AdminLTE 4 (Bootstrap 5) + Chart.js 4 + WebSocket | owner request |
| Deploy | docker compose, image push → registry lokal `192.168.88.92:5000` | migrasi = pull + `up -d` |
| Timezone | **Asia/Jakarta (WIB)** semua container (`TZ=`) | owner request |
| SNMP | `pysnmp-lextudio` (BUKAN `pysnmp` PyPI yang stale) | tech-watch |
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
4. **SNMP**: probe pertama wajib `sysObjectID 1.3.6.1.2.1.1.2.0` (timeout 2s ×2 → skip device). Community read-only cukup. Simpan raw OID di JSONB supaya device-type baru bisa di-re-match tanpa re-scan.
5. **Idempotent ingest**: 2 push identik (sha body sama, <1 interval) → ACK tanpa insert duplikat.
6. **Secrets**: agent secret di-hash (bcrypt/sha256+pepper); credential SNMP terenkripsi at-rest; `.env` gitignored.
7. **WebSocket event names**: `asset.new`, `asset.update`, `asset.offline`, `scan.progress`, `scan.done`. Payload kecil (id + ringkasan); UI fetch detail via REST.
8. **Task scheduler contract**: `raniPush 192.168.88.92` exit code 0/1 saja (0=berhasil/terspool, 1=gagal fatal), tidak interaktif, tidak butuh admin untuk field utama (fallback null, jangan crash).
9. **Git**: Conventional Commits (`feat:`, `fix:`, `docs:`), commit per milestone CHECKLIST.
10. **Bukti dulu baru centang**: curl output / docker logs / query DB = bukti. Jangan klaim done tanpa verifikasi hasil di sistem nyata.

## 5. Cara run dev
```bash
cd /root/RaniProject/ProjectDev
cp .env.example .env          # isi POSTGRES_PASSWORD, RANI_INGEST_PEPPER
docker compose up -d          # api :8091, UI http://192.168.88.92:8091
# agent dev test (tanpa exe):
python agent/raniPush.py --collect > payload.json
python agent/raniPush.py 192.168.88.92 --from-file payload.json
```

## 6. Keputusan arsitektur tercatat (ADR-mini)
- **ADR-D1**: push-model dulu, agentless scan menyusul → memangkas kebutuhan kredensial domain/WMI remote; SNMP tetap agentless-pull.
- **ADR-D2**: HTTP by-IP + HMAC (bukan TLS) untuk LAN; TLS opsional via nginx nanti — jangan blok desain karena ini.
- **ADR-D3**: UI server-rendered (Jinja2+htmx) bukan SPA → 1 container, tanpa node build stage.
- **ADR-D4**: satu service `worker` menjalankan ingest-consumer + scanner scheduler; pecah lagi kalau tercekik.

## 7. Kontak konteks
- Analisis Lansweeper + blueprint: `../baseOn/analysis results.md`
- Repo REA (reverse-engineer toolkit; referensi discipline kontrak JSON-schema): `..`
- Fondasi RANI lama (pattern RBAC/FastAPI yang boleh di-reuse sebagai referensi baca-saja): `/root/rani` — **jangan tulis kode aplikasi ke sana**, ProjectDev ini rumah baru.
