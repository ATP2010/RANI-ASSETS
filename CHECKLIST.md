# RANI — ProjectDev Checklist (v1)
> Status: [ ] todo · [~] in progress · [x] done. Update file ini setiap menyelesaikan task — ini source-of-truth progres.

## F0 — Spike raniPush (Windows collector)
- [ ] F0.1 `raniPush --collect` : kumpulkan identity (MachineGuid, hostname, domain) via registry/subprocess
- [ ] F0.2 Hardware via WMI (`wmic` deprecated → pakai PowerShell `Get-CimInstance`): CPU, RAM, disk, motherboard/serial, BIOS, GPU, monitor
- [ ] F0.3 OS info: caption, version, build, install date, locale, timezone, uptime
- [ ] F0.4 Network: MAC, IPv4, DNS, gateway, DHCP per interface
- [ ] F0.5 Software list: registry Uninstall HKLM+HKCU (+ WMI Win32_Product skip — mahal)
- [ ] F0.6 Security posture: Defender state, firewall profile, BitLocker, TPM, secure boot
- [ ] F0.7 Users: primary user, last logons, local admins
- [ ] F0.8 Output JSON validasi terhadap `schema/agent_payload_v1.json`
- [ ] F0.9 `raniPush <targetIP>` : POST + HMAC + retry/spool `%PROGRAMDATA%\Rani\spool\`
- [ ] F0.10 Test di 1 PC user nyata → payload masuk ke echo endpoint dev

## F1 — Server ingest + reconciler + UI dasar
- [ ] F1.1 Scaffold `docker compose`: api (FastAPI+gunicorn), worker, postgres 16, redis 7, timezone Asia/Jakarta
- [ ] F1.2 Alembic migrations skema `rani_inventory` (lihat AGENTS.md §DB)
- [ ] F1.3 `POST /api/v1/enroll` (token sekali-pakai → agent_id + secret)
- [ ] F1.4 `POST /api/v1/ingest/push` : verify HMAC+timestamp+nonce, rate-limit, enqueue Redis
- [ ] F1.5 Worker ingest: upsert asset (reconcile machine_id→serial→MAC→hostname), software DELTA (events), hw components, users, security_state
- [ ] F1.6 `GET /api/v1/assets` + `GET /api/v1/assets/{id}` (detail per tab)
- [ ] F1.7 UI: login (session cookie, bcrypt) + RBAC 3 role (admin/operator/reader)
- [ ] F1.8 UI: Asset list (search/filter/sort, status online/offline badge)
- [ ] F1.9 UI: Asset detail tabs — Overview/Hardware/Software/Users/Security/History
- [ ] F1.10 WebSocket hub `/ws` + broadcast event `asset.new`, `asset.offline`, `ingest.done`

## F2 — SNMP network scan (raniScan) + dashboard
- [ ] F2.1 Worker `pysnmp-lextudio`: probe sysObjectID `.1.3.6.1.2.1.1.2.0` → skip bila timeout
- [ ] F2.2 SNMP v1/v2c + v3 credential vault (terenkripsi at-rest), mapping per subnet/device-group
- [ ] F2.3 Pull: system group, ifTable (incl. MAC, speed, oper status), ipNetToMedia (ARP), entity MIB (serial/firmware)
- [ ] F2.4 Bridge MIB (dot1dTpFdb) → MAC-per-port → tabel `endpoint_port_mappings` → topologi L2
- [ ] F2.5 IP range target mgmt + jadwal scan + on-demand scan dengan progress via WebSocket
- [ ] F2.6 Hasil SNMP masuk reconciler yang sama (source=`snmp`) → device jadi asset type `network`
- [ ] F2.7 Dashboard: Chart.js (OS mix, asset trend 30h, top software, online/offline donut, software changes) realtime via WS
- [ ] F2.8 Printer enrichment (host-resources MIB / JetDirect OID)

## F3 — Ops & distribusi
- [ ] F3.1 Build raniPush → single exe (PyInstaller), silent install + Task Scheduler registration (`schtasks /create ... raniPush 192.168.88.92 /sc:hourly`)
- [ ] F3.2 Enrollment token UI + agent revoke + agent version visibility
- [ ] F3.3 Remote config interval (server respons `next_interval_s`)
- [ ] F3.4 Retention jobs: raw payload 90 hari, partisi software_reports
- [ ] F3.5 CSV export semua view; report builder sederhana (query template)
- [ ] F3.6 Image docker push → registry `192.168.88.92:5000/rani-{api,worker,ui}:latest` + runbook migrasi
- [ ] F3.7 Backup schedule postgres (pg_dump harian ke volume)

## F4 — Backlog (nilai tambah, belum dijanjikan)
- [ ] Linux collector (dmidecode/dpkg/rpm)
- [ ] Vulnerability insights: software CPE → OSV/NVD match
- [ ] Lifecycle/EOL insights (endoflife.date data)
- [ ] Webhooks + read-only GraphQL/REST query API + MCP server
- [ ] Discovery pasif tambahan: mDNS/SSDP/UPnP, HTTP banner
- [ ] Software normalization fuzzy + vendor alias table
- [ ] License/SAM module
- [ ] SSO (OIDC/AD LDAPS)

---
**Definition of Done per task:** ada bukti test nyata (curl output / screenshot / log), DB terisi benar, tidak ada regression di task sebelumnya.
