# RANI — Analysis: Lansweeper → Blueprint Aplikasi Serupa
**Date:** 2026-11-13 · **Author:** Hermes (senior IT dev pass) · **Location:** `/root/RaniProject/baseOn/`
**Goal:** Bangun aplikasi mirip Lansweeper bernama **Rani**, inti loop-nya: **`lspush`** (agent di PC user mengirim data) → **server menangkap** → **detail ditampilkan di dashboard**.

---

## 1. Apa itu Lansweeper (hasil analisis)

** positioning:** "Cyber Asset Intelligence Platform" — discovery + inventory + insights untuk IT/OT/cloud. 15+ tahun development, fokus ke *agentless scanning* sebagai differentiator, tapi punya agent untuk work-from-home.

### 1.1 Feature map (dari lansweeper.com/product + pricing)

| Layer | Fitur |
|---|---|
| **Discovery** | IT discovery (scan engine), OT discovery, Cloud discovery, **Agent discovery**, Discovery connectors (SCCM/Intune/AirWatch/G-Suite MDM), Traffic sensor (passive), Credential-free Device Recognition (CDR), AI usage tracking, IP range coverage |
| **Inventory** | Data reconciliation (dedup multi-source), normalization (software title/version/vendor/model/firmware), asset profiles, groups/classification, cleanup rules, custom fields + attachments |
| **Insights** | BI dashboards, report builder, diagrams (topologi), vulnerability insights, lifecycle/EOL, SAM (license), collective intelligence, Lens Chat (NL query) |
| **Integrations & Automation** | **GraphQL Data API + Platform API**, webhooks, Flow Builder (workflow), bulk export, **Lens MCP Server** (akses AI agent) |
| **Admin & Security** | RBAC granular, asset scopes, SSO, MFA, multi-region hosting, branding |

### 1.2 Arsitektur (Lansweeper Classic, on-prem — terdokumentasi resmi)

```
┌────────────┐   WMI/SNMP/SSH/SNMPv3/vCenter   ┌─────────────────┐
│  Devices   │ ◄────────(agentless pull)────── │  Scan Server(s) │
└────────────┘                                  └────────┬────────┘
┌────────────┐      HTTPS push (agent)                   │ writes
│  Windows   │ ─────────────────────────────────► ┌──────▼──────┐      ┌────────────┐
│  Agent     │                                    │ MS SQL DB   │ ◄──► │ Web Console│ (IIS)
└────────────┘                                    └─────────────┘      └────────────┘
```

- **Database** — pusat (MSSQL; 1 DB per instalasi)
- **Scanning Service** — engine agentless: WMI (Windows), SNMP (network device), SSH (Linux/Mac), vCenter/ESXi API; juga deployment, email, warranty lookup, DB cleanup
- **Web console** — visualisasi + konfigurasi
- **Agent** — opsi untuk device di luar jaringan kantor; **push data via HTTPS**

### 1.3 Reconciliation engine (pola penting yang harus kita tiru)

Identitas device = **identifier hardware stabil**, BUKAN IP:
1. Match **serial + make + model** (agent/WMI scan)
2. Match **MAC address** (SNMP/CDR/OT)
3. Match **hostname/domain**
IP-based matching ada tapi *disabled by default, evaluated last*. Multi-source merge → 1 asset record + view "Reconciliation" berisi semua source + confidence + timestamp.

### 1.4 Model bisnis (konteks, bukan target teknis)
Free ≤100 aset · Starter ~€245/bln (2.000 aset) · Pro ~€449/bln (+vuln/lifecycle, 3 instalasi) · Enterprise ≥10.000. Asset billable = device mandiri; komponen (disk, peripheral) tidak.

---

## 2. Gap analysis: Lansweeper vs kebutuhan Rani

| Aspek | Lansweeper | **Rani (kebutuhan user)** |
|---|---|---|
| Model pengumpulan | Agentless pull (WMI/SNMP) = kompleks, butuh kredensial domain | **Agent push (`lspush`)** = jauh lebih sederhana, firewall-friendly, jalan untuk PC di luar kantor |
| Kredensial device | Kelola credential vault per protokol | **Tidak perlu** — agent baca datanya sendiri via API OS lokal |
| Discovery pasif (SNMP scan jaringan) | Core | Fase 2+ (sudah ada di spec RANI lama: SNMP/LLDP) |
| Server menerima & menyimpan | MSSQL | **PostgreSQL** (sudah live di /root/mariadb stack & rani compose) |
| Tampilan detail | Web console IIS / SaaS | **Web dashboard self-hosted** |

**Keputusan arsitektur #1:** Rani MVP = *agent-push inventory*, bukan replika scan engine. Ini memangkas ±70% kompleksitas Lansweeper sambil tetap dapat 80% nilai (inventory hardware/software/user yang akurat). Agentless SNMP discovery menyusul sebagai sumber data kedua di belakang reconciliation layer yang sama.

---

## 3. Blueprint Rani

### 3.1 Komponen

```
PC User (Windows/Linux)                     Server Rani (Docker, LXC 192.168.88.92)
┌──────────────────────┐                    ┌─────────────────────────────────────┐
│ lspush agent         │   HTTPS POST /ingest│ ┌───────────┐  ┌──────────────────┐ │
│ • collect (WMI/      │ ──────────────────► │ │ API       │─►│ PostgreSQL       │ │
│   dmidecode/registry)│   JSON + HMAC sig   │ │ ingest +  │  │ schema: assets,  │ │
│ • schedule (systemd/ │   + enroll token    │ │ query     │  │ software, hw,    │ │
│   Task Scheduler)    │                    │ │ (FastAPI) │  │ events, agents   │ │
│ • spool offline →    │◄── config/update ── │ └───────────┘  └────────┬─────────┘ │
│   retry + backoff    │                    │ ┌───────────┐  ┌────────▼─────────┐  │
└──────────────────────┘                    │ │ Web UI    │  │ Reconciler       │  │
                                            │ │ (React/   │  │ (dedup by serial/│  │
                                            │ │ dashboard│  │  MAC/hostname)   │  │
                                            │ │ + detail)│  └──────────────────┘  │
                                            │ └───────────┘   Redis (queue/cache) │
                                            └─────────────────────────────────────┘
```

### 3.2 `lspush` — agent di PC user

**Teknologi:** Python 3 stdlib-first (packaging: PyInstaller exe untuk Windows, single binary untuk Linux) — tim sudah Python (FastAPI stack RANI).

**Kumpulan data per scan:**

| Group | Windows source | Linux source |
|---|---|---|
| Identity | MachineGuid (registry), hostname, domain | `/etc/machine-id`, hostname |
| Hardware | WMI: `Win32_ComputerSystemProduct` (serial, vendor, model), `Win32_Processor`, `Win32_PhysicalMemory`, `Win32_DiskDrive`, GPU, monitor/EDID | `dmidecode`, `/proc/cpuinfo`, `/sys/block`, `lspci`, `lsusb` |
| OS | `Win32_OperatingSystem` (caption, version, build, install date, locale, timezone) | `/etc/os-release`, uname, uptime |
| Network | `Win32_NetworkAdapterConfiguration` (MAC, IP, DNS, gateway, DHCP) | `ip`, sysfs MAC |
| Software | Registry Uninstall keys (HKLM/HKCU) + optionally Get-AppxPackage | `dpkg -l` / `rpm -qa` / `pacman -Q` + flatpak/snap |
| Users |最后登录 users, logged-on user, local admins | `lastlog`, group members |
| Security posture | Defender/AV state, firewall profile, BitLocker, Uptime, pending reboot (registry keys) | — |
| System | BIOS/UEFI version, secure boot, TPM, domain join status | systemd versions |

**Protocol push (yang ditangkap server):**

```json
POST /api/v1/ingest/push
Headers:
  X-Rani-Agent-Id:    <assigned at enrollment>
  X-Rani-Digest:      sha256:<body hash>
  X-Rani-Signature:   hmac_sha256(agent_secret, timestamp + nonce + body)
  X-Rani-Timestamp:   2026-11-13T20:32:00Z   (toleransi skew ±300s)
Body:
{
  "schema_version": 1,
  "agent_version": "0.1.0",
  "collected_at": "...",
  "identity": { "machine_id": "...", "hostname": "DESKTOP-X", "domain": "RKA.LOCAL" },
  "hardware": { "serial": "...", "vendor": "LENOVO", "model": "ThinkPad T14",
                "cpu": [...], "memory": [...], "disks": [...], "monitors": [...] },
  "os": { "family": "windows", "caption": "Windows 11 Pro", "version": "23H2", "build": "22631" },
  "network": { "interfaces": [ { "mac": "...", "ipv4": "...", "dns": [...] } ] },
  "software": [ { "name": "...", "version": "...", "vendor": "...", "install_date": "...", "uninstall_string_hash": "..." } ],
  "users": { "primary": "...", "last_logons": [...], "local_admins": [...] },
  "security": { "av": "Defender", "av_up_to_date": true, "firewall": "on", "bitlocker": "on", "tpm": "2.0", "secure_boot": true },
  "system": { "uptime_s": 86400, "bios_version": "...", "pending_reboot": false }
}
Response: 202 { "asset_id": "...", "report_id": "...", "next_interval_s": 3600 }
```

**Enrollment (bootstrap trust):** admin generate *enrollment token* per batch/PC di UI → agent di-install dengan token sekali-pakai → server membuat `agent_id` + `agent_secret` (disimpan di DPAPI/credential store lokal). Revocation per-agent di UI. Retry: push gagal → spool di `%PROGRAMDATA%\Rani\spool\`, backoff eksponensial, max 7 hari.

**Interval:** default 1 jam (server bisa override via `next_interval_s` di response — remote-controllable), plus push-on-startup (PC baru nyala langsung lapor = *lihat apa yang hari ini ada di jaringan* tanpa scan).

### 3.3 Server ingest

**Stack:** FastAPI + PostgreSQL + Redis (sama persis dengan fondasi RANI yang sudah ada → reuse `identity`, RBAC, audit schemas).

Pipeline: `validate sig → rate-limit per agent → enqueue (Redis stream) → worker`
1. **Upsert asset** — identity match berjenjang (tiru Lansweeper): `machine_id` → `serial` → `MAC` → `hostname` (IP terakhir, hanya korelasi bukan kunci). Duplicate → merge + catat di `asset_sources`.
2. **Delta software** — bukan snapshot-per-run (pelajaran dari spec RANI: 4,3 jt baris/hari). Simpan `software_install` + event `installed/uninstalled/changed` berdasar hash diff vs report sebelumnya.
3. **HW components** — upsert keyed (asset_id, class, key), komponen hilang → status `removed`, riwayat tetap.
4. **Stale detection** — agent heartbeat > X jam → asset status `offline` (ini pengganti "cleanup rules" Lansweeper).
5. **Normalization hook** — fase 1: trim/lowercase/vendor alias table sederhana; fase 2: fuzzy title matching.

### 3.4 Web UI — "ditangkap lalu ditampilkan details"

Halaman MVP (urutan bangun):
1. **Asset list** — tabel searchable/sortable: hostname, IP, OS, user, status online, last seen, software count. Filter: type/OS/location/subnet.
2. **Asset detail** — tab: Overview (identitas+status) · Hardware (cpu/ram/disk/gpu/monitor + serial + warranty field) · Software (list + install/uninstall history) · Users · Security (AV/firewall/BitLocker/patch state) · Network (interfaces) · Reports (riwayat push + delta per report) · Sources (reconciliation trace).
3. **Dashboard** — total asset, online/offline, OS mix, top software, recent changes (uninstall kemarin), license exposure sederhana.
4. **Agent mgmt** — enrollment token, list agent + secret status, revocation.
5. **Export** — CSV per view (bulk export ala Lansweeper).

Fase lanjut: report builder, diagrams/topologi, vuln insights (CPE match dari software list → NVD/OSV), integrasi Jira/ServiceDesk webhook, MCP server (sudah jadi arah RANI — query asset via AI agent).

### 3.5 Skema DB minimum (PostgreSQL, schema `rani_inventory`)

```sql
agents(id, machine_id, secret_hash, enrolled_at, revoked_at, last_seen, config_json)
assets(id, asset_type, hostname, os_family, os_caption, serial, primary_mac,
       ip_last, status, first_seen, last_seen, agent_id, attrs_jsonb)
asset_sources(asset_id, source, evidence_jsonb, confidence, matched_on, ts)
software_reports(id, asset_id, agent_id, pushed_at, payload_sha, raw_jsonb)  -- retention window
software(asset_id, name_norm, name_raw, version, vendor, install_date,
         present BOOLEAN, first_seen, last_seen)
software_events(asset_id, software_id, event, at)         -- install/uninstall/change
hw_components(asset_id, class, key, attrs_jsonb, present, last_seen)
users_seen(asset_id, username, role, last_seen)
security_state(asset_id, checked_at, av, av_ok, firewall, disk_encryption, tpm, ...)
```
Partition `software_reports` per bulan; raw payload dibuang >90 hari (yang permanen: hasil delta). Ini menjawab concern retention di spec lama.

### 3.6 Kenapa ini sesuai "senior dev lens"

- **Push > pull untuk MVP**: tidak perlu seed kredensial domain/WMI remote; tembus NAT/VPN remote worker; server hanya buka 1 endpoint. (Lansweeper sendiri menempatkan agent untuk use-case ini.)
- **Idempotent + signed ingest**: replay attack dan duplicate push netral sejak hari 1 (HMAC + nonce + sha body).
- **Schema-versioned payload**: agent lama tidak akan pernah break server baru; migrasi mulus.
- **Delta model sejak awal**: scaling 1.000 endpoint (target RANI) ≈ 1.000 push/jam ≈ ringan, dan DB tidak membengkak.
- **Reuse fondasi RANI**: Postgres/Redis/nginx/gunicorn compose pattern, RBAC 9-perm, audit log — tidak mulai nol.

---

## 4. Roadmap eksekusi

| Fase | Deliverable | Estimasi |
|---|---|---|
| **F0 — Spike** | `lspush --collect` (Windows) cetak JSON lengkap + `POST` ke endpoint echo; verifikasi field apa yang bisa diambil tanpa admin/elevated | 2–3 hari |
| **F1 — Ingest loop** | FastAPI `/ingest/push` + enrollment + HMAC + Postgres upsert + reconciler berjenjang; UI: asset list + detail minimal | 1–2 minggu |
| **F2 — Visibility** | Dashboard, software delta + history, users, security state, CSV export, stale/offline logic, Linux collector | 2 minggu |
| **F3 — Ops** | Agent installer (MSI + GPO push / SCCM), remote config interval, RBAC+SSO dari fondasi RANI, retention jobs | 2 minggu |
| **F4+** | SNMP/CDR passive discovery sebagai source #2, vuln insights, report builder, MCP server | backlog |

**Catatan metode REA (`/root/RaniProject`):** untuk fase berikutnya, pola capture bisa dipakai langsung — `docs/guides/web/web-network-captures.md` + `website-script-export.md` untuk membedah payload GraphQL Lansweeper Data API (developer.lansweeper.com) saat kita mendesain API query Rani agar kompatibel pola pasar; dan repo ini sendiri adalah referensi bagus untuk disiplin kontrak JSON-Schema + versioning yang dipakai di §3.2.

---

## 4b. SNMP network-device scanning (kebutuhan owner — pola Lansweeper, terverifikasi docs.lansweeper.com)

Lansweeper scanning perangkat jaringan bekerja begini (kita tiru untuk **raniScan**):
- **UDP 161**, SNMP **v1/v2c** (community string read-only cukup; default banyak device: `public`) dan **v3** (username+auth).
- **Probe pertama = OID `1.3.6.1.2.1.1.2.0` (sysObjectID)**. Tidak jawab → device dianggap SNMP-off, skip. Jawab → vendor/device-type diketahui dari OID tree.
- Lalu tarik: `system` group (descr, objectid, name, location, contact, uptime), `interface` table (ifDescr/ifType/ifMACAddress/ifSpeed/ifOperStatus/ifInOctets/ifOutOctets → bandwidth), `ipNetToMediaTable` (ARP: IP↔MAC↔interface → **discovery device di belakang switch**), bridge MIB (dot1dTpFdbPort → **MAC per port switch** → topologi Layer-2), entity MIB (serial, firmware, modul), printer host-resources/ JetDirect.
- Lansweeper juga supporting passif protocol lain (mDNS/SSDP/UPnP/HTTP banner) — masuk backlog Rani, SNMP dulu.

**Keputusan owner: SNMP scanner masuk F1/F2, bukan backlog jauh.** Implementasi: worker `pysnmp-lextudio` (pysnmp PyPI stale — catatan tech-watch lama tetap berlaku), IP-range target + credential vault per device-group, jadwal scan, hasil masuk reconciler yang sama dengan raniPush (`network` source).

## 4c. Stack tambahan yang diputuskan owner
- **UI**: AdminLTE-style modern — Bootstrap 5 + AdminLTE 4 (tema) + **Chart.js 4** (grafik modern) + **FastAPI WebSocket** untuk realtime (counter dashboard, live scan progress, notifikasi asset baru/offline). Server-rendered Jinja2 + htmx untuk partial refresh — tetap sederhana, tanpa build-step React.
- **DB**: **PostgreSQL** (JSONB untuk payload agent + MIB hasil SNMP, partisi, replikasi mudah). MariaDB yang sudah live di server dipakai untuk reporting/analytics opsional saja.
- **Deploy**: docker compose + push ke **registry lokal `192.168.88.92:5000`** (pola sama dengan wifi-guard) → migrasi = `docker pull` + `compose up`.

## 5. Keputusan owner (SIGNED-OFF 2026-11-13)

1. **Nama agent** → **`raniPush`** (CLI: `raniPush <targetIP>`, dipasang di Windows Task Scheduler via cmd).
2. **Endpoint** → **tanpa DNS/TLS wajib**: target di-set manual by IP, contoh `raniPush 192.168.88.92`. HTTP internal LAN; HMAC signature tetap jalan (auth tidak bergantung TLS). Opsional HTTPS via nginx self-hosted nanti.
3. **Platform** → Windows dulu (F0/F1), Linux menyusul; **SNMP network scan masuk scope** (§4b) untuk switch/router/printer/AP — fitur wajib ala Lansweeper.
4. **Stack** → FastAPI + PostgreSQL, code di subfolder **`ProjectDev/`** (git repo sendiri), deploy docker compose → push registry lokal `192.168.88.92:5000`; migrasi server = `docker pull` + `compose up -d`.
5. **UI** → AdminLTE 4 (Bootstrap 5) + Chart.js + **WebSocket realtime** untuk dashboard.

---
*Sources: lansweeper.com (homepage, /product/, /pricing/), docs.lansweeper.com (components-and-architecture, reconciliation engine), developer.lansweeper.com, MSP masterclass blog (CDR vs credential scan). All fetched 2026-11-13.*
