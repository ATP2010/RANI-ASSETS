# RANI — ProjectDev Checklist (v1)
> Status: [ ] todo · [~] in progress · [x] done. Update file ini setiap menyelesaikan task — ini source-of-truth progres.

## F0 — Spike raniPush (Windows collector)
- [x] F0.1 `raniPush --collect` : identity (MachineGuid/hostname/domain) — Windows via `winreg`, Linux via `/etc/machine-id` (terverifikasi Linux)
- [~] F0.2 Hardware via WMI (`Get-CimInstance`): CPU, RAM, disk, motherboard/serial, BIOS, GPU, monitor — kode Windows ada, belum diuji di PC nyata; Linux via `/proc`, `/sys/block`, dmidecode (terverifikasi)
- [~] F0.3 OS info: caption, version, build, install date, locale, timezone, uptime — Linux terverifikasi; Windows belum diuji
- [x] F0.4 Network: MAC, IPv4, DNS, gateway, DHCP per interface (Linux `ip -j`, Windows CIM)
- [x] F0.5 Software list: Linux dpkg/rpm (799 paket terkirim); Windows registry Uninstall HKLM+HKCU
- [~] F0.6 Security posture: Defender/firewall/BitLocker/TPM/secure boot — kode Windows ada (belum diuji); Linux mengirim null
- [x] F0.7 Users: primary/logged-on/local admins (Linux `who` terverifikasi)
- [x] F0.8 Output JSON validasi terhadap `schema/agent_payload_v1.json` (unit test `PayloadContractTest`)
- [x] F0.9 `raniPush <targetIP>` : POST + HMAC + retry/spool (`~/.rani`/`%PROGRAMDATA%\Rani\spool`)
- [x] F0.10 Test push nyata → masuk `software_reports` + asset ter-reconcile (lihat bukti F1)

## F1 — Server ingest + reconciler + UI dasar
- [x] F1.1 Scaffold `docker compose`: api (FastAPI+uvicorn 2 worker), worker, postgres 16.4, redis 7.4, `TZ=Asia/Jakarta`, project `rani-inv`, port 8091
- [x] F1.2 Alembic migration skema `rani_inventory` (revision `0001_initial`, 14 tabel)
- [x] F1.3 `POST /api/v1/enroll` (token sekali-pakai → agent_id + secret; token hash sha256, TTL)
- [x] F1.4 `POST /api/v1/ingest/push` : digest+timestamp+nonce wajib, HMAC opsional bila agent ter-enroll, rate-limit 30/min, idempotensi sha, enqueue Redis Stream
- [x] F1.11 Push **tanpa token** (agent 0.2+): agent dikenali dari `identity.machine_id`, auto-register baris agent mode `direct` (secret NULL), `RANI_TOKENLESS_PUSH=0` mengembalikan wajib-HMAC. Migration `0002_agent_secret_nullable`
- [x] F1.5 Worker ingest: upsert asset (reconcile machine_id→serial→MAC→hostname + konflik machine_id), software DELTA + drop-guard, hw components, users, security_state, network_interfaces, requeue sweeper, stale sweep
- [x] F1.6 `GET /api/v1/assets` + `GET /api/v1/assets/{id}` (+ `/api/v1/stats`, `/api/v1/agents`)
- [x] F1.7 UI login (session cookie DB, bcrypt) + RBAC 3 role (admin/operator/reader) + audit log + rate-limit login
- [x] F1.8 UI Asset list (search/filter/sort/pagination, badge online/offline)
- [x] F1.9 UI Asset detail tabs — Overview/Hardware/Software/Users/Security/Network/Reports/Sources
- [x] F1.10 WebSocket `/ws` (auth cookie) + event `asset.new`, `asset.update`, `asset.offline` via Redis pub/sub (terverifikasi menerima event saat push)

**Bukti F1 (2026-11-13, dev LXC):**
- push 202 → worker `processed`; asset `ct-hermes-01` (Ubuntu 24.04.5 LTS, 192.168.88.92, mac bc:24:11:e9:aa:71), 799 paket aktif
- delta: hapus 3 paket → `uninstalled +3`, ubah `adb` versi → event `changed`
- guard: payload software kosong ditolak jadi mass-uninstall (report error `software drop guard`)
- konflik identitas: machine_id beda + MAC sama → asset baru (tidak merge)
- negatif: secret salah 401, digest salah 401, agent tak dikenal 401, replay nonce 409, payload invalid 422, duplikat sha 202 `duplicate:true`
- revoke agent → push 401; WS tanpa cookie ditolak
- `scripts/smoke_test.py` → semua cek PASS

## F2 — SNMP network scan (raniScan) + dashboard
- [ ] F2.1 Worker `pysnmp-lextudio`: probe sysObjectID `.1.3.6.1.2.1.1.2.0` → skip bila timeout
- [ ] F2.2 SNMP v1/v2c + v3 credential vault (terenkripsi at-rest), mapping per subnet/device-group
- [ ] F2.3 Pull: system group, ifTable (incl. MAC, speed, oper status), ipNetToMedia (ARP), entity MIB (serial/firmware)
- [ ] F2.4 Bridge MIB (dot1dTpFdb) → MAC-per-port → tabel `endpoint_port_mappings` → topologi L2
- [ ] F2.5 IP range target mgmt + jadwal scan + on-demand scan dengan progress via WebSocket (tabel `scan_targets` sudah disiapkan)
- [ ] F2.6 Hasil SNMP masuk reconciler yang sama (source=`snmp`) → device jadi asset type `network`
- [~] F2.7 Dashboard: Chart.js (OS mix, top software, push trend 24h) + realtime WS — selesai; asset trend 30h & online/offline donut: donut status sudah ada, trend aset per jam belum
- [ ] F2.8 Printer enrichment (host-resources MIB / JetDirect OID)

## F3 — Ops & distribusi
- [x] F3.1 Build raniPush → single exe PyInstaller (`agent/raniPush.spec`, `scripts/build-exe.sh` via Wine, workflow GitHub Actions Windows) + `scripts/install-agent.ps1` (copy + Task Scheduler, `-Token` opsional). Exe terverifikasi di Wine: `--collect` payload valid skema, push 202 tanpa token (auto-register mode `direct`) dan jalur enroll+HMAC tetap PASS. Tersedia juga `raniPush-signed.exe` (osslsigncode, sertifikat internal + timestamp, `scripts/sign-exe.sh` + `install-cert.ps1`) dan `raniPush-portable.zip` (Python embeddable + .cmd) untuk PC yang memblokir exe. **Belum** dijalankan di PC Windows nyata (MSI/GPO belum).
- [x] F3.2 Enrollment token UI + agent revoke (UI + API); token kini opsional — `RANI_TOKENLESS_PUSH=0` untuk mewajibkan HMAC
- [x] F3.8 Unduhan agent dari browser: panel **Download agent** di `/agents` (signed exe, exe unsigned, cert, `install-cert.ps1`, portable zip) via `/downloads/<nama>` — allowlist nama, wajib login, compose mount `./release` + `./scripts` read-only
- [ ] F3.3 Remote config interval (server kirim `next_interval_s`; agent sudah menyimpannya — UI belum)
- [ ] F3.4 Retention jobs: raw payload 90 hari, partisi software_reports
- [x] F3.5 CSV export asset view (`/export/assets.csv`)
- [x] F3.6 Script push image → registry `192.168.88.92:5000/rani-server` (`scripts/push-registry.sh`; belum dijalankan)
- [ ] F3.7 Backup schedule postgres (pg_dump harian ke volume)

## F4 — Backlog (nilai tambah, belum dijanjikan)
- [ ] Linux collector — **sudah jalan** (dpkg/rpm, /proc, sysfs); macOS belum
- [~] Vulnerability insights: software CPE → OSV/NVD match
- [ ] Lifecycle/EOL insights (endoflife.date data)
- [ ] Webhooks + read-only GraphQL/REST query API + MCP server
- [ ] Discovery pasif tambahan: mDNS/SSDP/UPnP, HTTP banner
- [x] Software normalization dasar (trim/lowercase/collapse space, `name_norm` unik per asset)
- [ ] License/SAM module
- [ ] SSO (OIDC/AD LDAPS)

---
**Definition of Done per task:** ada bukti test nyata (curl output / screenshot / log), DB terisi benar, tidak ada regression di task sebelumnya.