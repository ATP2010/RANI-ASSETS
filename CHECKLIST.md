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
- [x] F1.12 **Custom reports** (menu Reports): SQL SELECT dari user disimpan di tabel `reports`, dieksekusi role DB read-only `rani_report` (migration `0003_reports`), hasil JSON + grid dengan filter per kolom, export CSV, 3 report contoh, audit `report.*`
- [x] F1.11 Push **tanpa token** (agent 0.2+): agent dikenali dari `identity.machine_id`, auto-register baris agent mode `direct` (secret NULL), `RANI_TOKENLESS_PUSH=0` mengembalikan wajib-HMAC. Migration `0002_agent_secret_nullable`
- [x] F1.5 Worker ingest: upsert asset (reconcile machine_id→serial→MAC→hostname + konflik machine_id), software DELTA + drop-guard, hw components, users, security_state, network_interfaces, requeue sweeper, stale sweep
- [x] F1.6 `GET /api/v1/assets` + `GET /api/v1/assets/{id}` (+ `/api/v1/stats`, `/api/v1/agents`)
- [x] F1.7 UI login (session cookie DB, bcrypt) + RBAC 3 role (admin/operator/reader) + audit log + rate-limit login (role tetap; F5 menambah permission custom + login AD)
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
- report: 3 contoh ter-seed; run "Top software" → 20 baris/10 ms, filter kolom "microsoft" → 9 tampil; query 5000 baris → dipotong 1000 (`truncated`); `DELETE FROM assets` ditolak guard "hanya query SELECT"; heavy query → `statement_timeout` 8s → 400 + `last_error`; psql `rani_report` INSERT → `cannot execute INSERT in a read-only transaction`; `select password_hash from app_users` → `permission denied`; export CSV `text/csv`

## F2 — SNMP network scan (raniScan) + dashboard
- [x] F2.1 Klien SNMP **stdlib** (`app/snmp.py`): BER encode/decode, GET multi-varbind, GETNEXT walk, timeout+retry — tanpa dependency baru. Probe sysObjectID `1.3.6.1.2.1.1.2.0` dulu, host tanpa balasan = `timeout`
- [x] F2.2 SNMP **v1/v2c** + credential vault: community terenkripsi Fernet di `scan_groups.community_enc`, per grup (bukan v3 — belum)
- [x] F2.3 Pull system group (sysDescr/sysName/sysUpTime/ifNumber), entity MIB (serial/model/vendor), custom OID termasuk walk tabel (`ifDescr.*`, `ifOperStatus.*`). ifTable MAC/speed + ARP otomatis belum
- [x] F2.4 Bridge MIB (dot1dTpFdb) → MAC-per-port → tabel `endpoint_port_mappings` → topologi L2: `collect_bridge_fdb()` (dot1d dulu, fallback dot1q + `dot1qVlanFdbId`), MAC dari indeks OID, GETBULK v2c + fallback GETNEXT v1, `present=false` untuk MAC hilang, halaman **Agents → Port map** + tab Port map di asset network + `GET /api/v1/network/port-map` / `lookup`. Toggle per grup (`scan_groups.fdb_enabled`). Graf switch-to-switch belum (menunggu LLDP/CDP, F2.9)
- [x] F2.4b **Kolom Port / Switch di menu Assets**: daftar `/assets` menampilkan lokasi L2 per PC (`Gi0/2 · <ip switch>`, maks 2 + "+N lagi") dan ringkasan untuk switch (`N MAC · M known · P port` → tab Port map); CSV `l2_location`; `/api/v1/assets` `l2_location[]`; fallback cocok via MAC asset (`primary_mac` + `network_interfaces.mac`) bila `endpoint_asset_id` belum tertaut; tab Port map detail switch diurutkan natural (`Gi1/0/2` < `Gi1/0/10`)
- [x] F2.5 IP range target mgmt (`/agents/groups`: CRUD grup, CIDR/range/IP, toggle) + custom OID mgmt + scan on-demand dengan progress WS (`scan.progress`/`scan.done`) dan polling UI. Jadwal otomatis belum
- [x] F2.6 Hasil SNMP → asset `asset_type='network'` (identity serial→hostname→IP) + `scan_results` + `assets.attrs.snmp`; event `asset.new/update` ikut WS
- [x] F2.7 Dashboard: **Apache ECharts 5.5** (donut OS mix, donut online/offline, bar top software, area push 24 jam dengan bucket per jam WIB) + tooltip persen, toolbox simpan PNG, tema gelap/terang re-render, resize saat sidebar collapse; realtime WS refresh. Sisanya: tren jumlah aset per jam (bukan push) belum
- [ ] F2.8 Printer enrichment (host-resources MIB / JetDirect OID)

**Bukti F2 (2026-11-14, dev LXC):** scan grup uji `172.22.0.1:1161` (net-snmp 5.9.4 lokal) → status `done`, 1/1 host, `sysName=SW-TEST-01`, `ifNumber=28`, sysObjectID `1.3.6.1.4.1.8072.3.2.10`; custom OID GET (`1.3.6.1.2.1.1.4.0` = `admin@rani.local`) dan walk `ifDescr.*` (16 baris: lo/eth0/docker0/…) tersimpan di `scan_results.oid_values`; asset `network` dibuat + `attrs.snmp`; audit `scan.start`. Unit test SNMP (fake agent UDP) 7 test: GET multi-OID, walk subtree, timeout, version field v1/v2c, parser range. Scan user `10.194.7.0/26` (Vlan_470) selesai 62/62 host, 0 menjawab SNMP (perlu cek community/ACL di perangkat).

**Bukti F2.4b (2026-11-15, dev LXC):** kolom **Port / Switch** di `/assets`: `45U5-X415` → `Gi1/0/1 · 172.18.0.1`, `ct-rani` → `Gi1/0/2 · 172.18.0.1`, `ct-hermes-01` → `Gi1/0/3 · 172.18.0.1`, switch `SW-PORTMAP-01` → `10 MAC · 3 known · 4 port` (link ke tab Port map); tab Port map detail switch diurut natural (`Gi1/0/1`→`Gi1/0/2`→`Gi1/0/3`→`Gi1/0/48`, compname per port tampil: `45U5-X415`/`ct-rani`/`ct-hermes-01`); CSV `l2_location` (`Gi1/0/1 @ 172.18.0.1`) dan `/api/v1/assets.items[].l2_location[]` terisi; fallback cocok MAC asset ↔ `endpoint_port_mappings` (belum tertaut) bekerja tanpa scan ulang; halaman `/assets` 200, CSV 200, 35 unit test OK (4 skip).

**Bukti F2.4 (2026-11-15, dev LXC):** fake switch `SW-PORTMAP-01` (Cisco WS-C2960X-48FPS-L, BRIDGE-MIB, UDP 1610 → `172.18.0.1`) di grup `Port map dev` (`fdb_enabled=true`). Run `0fce4b07…` → `scan_results.fdb_count=10`, `stats={"bridges":1,"port_map_rows":10}`; run `cafd2fc7…` (ulang setelah FDB diubah) → 11 baris `endpoint_port_mappings`: 3 endpoint nyata tertaut (`45U5-X415` Gi1/0/1, `ct-rani` Gi1/0/2, `ct-hermes-01` Gi1/0/3), MAC multicast `01:00:5e:00:00:01` dibuang, status `self` di Gi1/0/48. Delta terverifikasi: `aa:bb:cc:00:11:22` (hilang) → `present=false`, `aa:bb:cc:00:11:88` masuk. API `GET /api/v1/network/port-map` → summary 10 MAC / 4 port / 3 known; `lookup?q=bc:24:11:e9` → Gi1/0/3 `ct-hermes-01`. UI `/agents/portmap` 200 (21.012 B, 1× badge `uplink?`), detail asset switch 200, riwayat scan menampilkan kolom Port map; role `rani_report` bisa `SELECT` 11 baris. Unit test `test_snmp_scan.py` 34 test OK (4 skip): GETBULK vs GETNEXT, v1 fallback, parsing indeks dot1d/dot1q (termasuk MAC printable), reject multicast/broadcast, truncation, probe dengan/tanpa FDB. Migration `0005_bridge_fdb` terpasang (`alembic_version=0005_bridge_fdb`).

## Riwayat pekerjaan sesi (Nov 2026)

| # | Pekerjaan | Commit | Bukti singkat |
|---|---|---|---|
| 1 | Agent 0.2 **tanpa token** (`raniPush <ip:port>`), auto-register mode `direct`, HMAC opsional, migration `0002` | `57b8647` | push 202 tanpa config; exe Wine push OK; 21 unit test |
| 2 | **Download agent dari browser** `/downloads/<nama>` (signed exe, cert, portable zip, script), mount read-only | `57b8647` | signed exe 7.686.056 B via HTTP 200 |
| 3 | Dashboard **Apache ECharts** (donut OS, status, bar top software, area push 24 jam) + bucket WIB | `10fc1ba` | 4 canvas, filter/legend, tema gelap re-render |
| 4 | **Sidebar mini persisten** (`sidebar-mini` + `data-enable-persistence`), ikon SVG, pra-paint anti-flash | `10fc1ba` | 74 px collapsed, bertahan pindah halaman |
| 5 | **Ikon aplikasi** (favicon, apple-touch, manifest, logo sidebar) + `scripts/make-icons.py` + `docs/branding.md` | `bbdbf8d`, `14618e8` | semua aset 200, brand 33/28 px |
| 6 | **Custom reports SQL** (menu Reports) + role DB read-only `rani_report`, guard, row cap, CSV, migration `0003` | `c1c85bf` | 20 baris/10 ms; DML ditolak; timeout 8s |
| 7 | **Submenu Agents + Scan SNMP** (grup IP CRUD, custom OID, scan on-demand + progress) + `docs/scan.md`, migration `0004` | (commit ini) | e2e net-snmp: 1/1 host, custom OID GET+walk, asset network |
| 8 | Waktu UI konsisten **WIB** (`fmt_dt` + trend/recent events) | `10fc1ba`, `c1c85bf` | last_seen 15:42 = WIB |
| 9 | **Deploy Docker Hub** (image pull & run, compose hub, env contoh, panduan) | (commit ini) | uji pull-and-run di port 8092: health ok, login, reports run, signed exe 7.686.056 B, role `rani_report` dibuat |
| 10 | **Halaman push: 2 jalur unduhan + panduan “blocked by your organization”** — portable jadi jalur A, kartu diagnostik SAC/ASR/WDAC + SHA256 artefak & publisher rule untuk IT, `artifact_sha256()` cache, `docs/agent-windows.md` §8 Solusi D + template permintaan IT | (commit ini) | smoke 28 cek LULUS (termasuk `download raniPush-portable.zip` 10.859.438 B dan `push: jalur portable + panduan blokir`); halaman 31.846 B; hash dirender = hash file (e062fc… / 121e5c… / 366d82…); 21 unit test OK |
| 11 | **Agent 0.2.1: identitas enroll tidak lagi menyeberang server** — `push_payload` membuang `agent_id`/`agent_secret` bila target ≠ server di config, flag `--reset-identity`, hint 401 “agent tidak dikenal”; portable zip dibuild ulang | (commit ini) | reproduksi sebelum: config `.92` + push ke `.85` → `401 agent tidak dikenal/direvoke`; sesudah patch: `push ok` (agent `98e86e45…` didaftarkan mode direct di .85), config bersih `{"server": "...85", "interval_s": 3600}`; zip 0.2.1 sha256 `051963dd…` |
| 12 | **F2.4 Port map L2** — `endpoint_port_mappings` + bridge FDB (dot1d/dot1q, GETBULK), MAC dari indeks OID, tautan ke asset via `primary_mac`, delta `present=false`, halaman `/agents/portmap` + tab asset + API `/network/port-map` & `/lookup`, toggle per grup, migration `0005`, `docs/scan.md` §3b | (commit ini) | fake switch UDP 1610: `fdb_count=10`, 11 baris, 3 endpoint tertaut, multicast dibuang, `self` Gi1/0/48; delta `aa:bb…22` → `present=false`, `aa:bb…88` masuk; lookup `bc:24:11:e9` → Gi1/0/3; 34 unit test OK; `rani_report` SELECT 11 |

## F3 — Ops & distribusi
- [x] F3.1 Build raniPush → single exe PyInstaller (`agent/raniPush.spec`, `scripts/build-exe.sh` via Wine, workflow GitHub Actions Windows) + `scripts/install-agent.ps1` (copy + Task Scheduler, `-Token` opsional). Exe terverifikasi di Wine: `--collect` payload valid skema, push 202 tanpa token (auto-register mode `direct`) dan jalur enroll+HMAC tetap PASS. Tersedia juga `raniPush-signed.exe` (osslsigncode, sertifikat internal + timestamp, `scripts/sign-exe.sh` + `install-cert.ps1`) dan `raniPush-portable.zip` (Python embeddable + .cmd) untuk PC yang memblokir exe. **Belum** dijalankan di PC Windows nyata (MSI/GPO belum).
- [x] F3.2 Enrollment token UI + agent revoke (UI + API); token kini opsional — `RANI_TOKENLESS_PUSH=0` untuk mewajibkan HMAC
- [x] F3.8 Unduhan agent dari browser: panel **Download agent** di `/agents/push` (signed exe, exe unsigned, cert, `install-cert.ps1`, portable zip) via `/downloads/<nama>` — allowlist nama, wajib login, compose mount `./release` + `./scripts` read-only
- [ ] F3.3 Remote config interval (server kirim `next_interval_s`; agent sudah menyimpannya — UI belum)
- [ ] F3.4 Retention jobs: raw payload 90 hari, partisi software_reports
- [x] F3.5 CSV export asset view (`/export/assets.csv`)
- [x] F3.6 Script push image → registry lokal `192.168.88.92:5000/rani-server` (`scripts/push-registry.sh`)
- [x] F3.9 **Deploy Docker Hub** `adhityatp/raniassets:v0.1.0` + `latest` (repo public, digest `sha256:06f96852…47215c`, 386 MB): image berisi API+worker+schema+docs+skrip+artefak agent, `docker-compose.hub.yml` (tanpa build/mount), `.env.hub.example`, `scripts/push-dockerhub.sh` (artefak → `docker/artifacts/` → build → tag latest → push), panduan `docs/deploy-dockerhub.md`
- [ ] F3.7 Backup schedule postgres (pg_dump harian ke volume)

## F4 — Backlog (nilai tambah, belum dijanjikan)
- [ ] Linux collector — **sudah jalan** (dpkg/rpm, /proc, sysfs); macOS belum
- [~] Vulnerability insights: software CPE → OSV/NVD match
- [ ] Lifecycle/EOL insights (endoflife.date data)
- [ ] Webhooks + read-only GraphQL/REST query API + MCP server
- [ ] Discovery pasif tambahan: mDNS/SSDP/UPnP, HTTP banner
- [x] Software normalization dasar (trim/lowercase/collapse space, `name_norm` unik per asset)
- [x] F4.4 **Actions (gaya Lansweeper)** di menu Assets & detail asset: hover hostname → popup overview (IP, MAC, OS, domain, serial, port/switch) + menu **Actions** (Buka HTTP/HTTPS, share `file:///IP/c$`, RDP `rdp://`, SSH, VNC; tombol salin `mstsc /v:…`/IP/MAC/hostname) — `app/actions.py` satu sumber, parameter `{ipaddress}/{fqdn}/{mac}/…`; tab Overview menampilkan **Terhubung ke** (switch + port + VLAN); docs [`docs/actions.md`](docs/actions.md)
- [ ] License/SAM module
- [ ] SSO (OIDC/AD LDAPS) — lihat F5.8

## F5 — Users & access management (selesai F5.1–F5.7; desain di [`docs/users.md`](docs/users.md))
> Menu **Users** (admin/perm-only) dengan login lokal + AD, role/permission custom, dan sync group AD. Implementasi selesai; bukti di bawah.
- [x] F5.1 **Model role & permission** (migration `0006_users_ad`): tabel `roles` + `app_user_roles`, seed `admin/operator/reader`, backfill `app_users.role`, katalog permission `modul.aksi` (21 kunci), resolver union + `require_perm()`; admin terkunci (semua permission, tidak bisa diubah/dihapus). Test: resolver union, anti-lockout (PATCH `roles=["reader"]` pada user guard terakhir → 409; role bawaan tidak bisa dihapus; migrasi round-trip `0006→0005→0006` teruji (downgrade mengembalikan kolom `role` + re-backfill). Migration `0006_users_ad` terpasang. Rapi
- [x] F5.2 **Halaman Users + API lokal**: daftar/cari/filter user, tambah (`bcrypt` cost 12, min `RANI_PASSWORD_MIN_LEN=12`), ubah properti + role, reset password (semua sesi dicabut), aktif/nonaktif, cabut semua sesi, hapus (ditolak bila ada jejak audit → redirect error); guard seed admin (403) + guard admin terakhir (409); audit `user.create|update|disable|enable|password_reset|role_change|delete`, target `rani-testuser` tercatat. Login polos = lokal saja; AD tidak bisa login dengan username polos
- [x] F5.3 **Halaman Role & akses + API custom role**: buat role custom (`helpdesk` — 409 saat dipakai user, 200 setelah kosong), duplikat, matriks permission per modul, override `admin` terkunci (POST → 403), jumlah user/mapping per role; hanya `roles.manage`; `GET /api/v1/roles` + `/api/v1/permissions`
- [x] F5.4 **AD connector**: form connector (NetBIOS/FQDN, URL LDAP/LDAPS, CA PEM, bind DN, bind password terenkripsi Fernet write-only, base DN, user/group filter, nested groups, interval); tombol **Test connection** (bind service + hitung user/grup) + browse group; `ldap://` diberi warning di UI; connector disimpan → `bind_password_enc` tidak pernah tampil balik (terverifikasi 0 kemunculan di HTML)
- [x] F5.5 **Mapping group → role + sync**: `directory_group_roles` (unique connector+DN), sync manual + interval (background loop 60s, advisory lock `pg_try_advisory_xact_lock(hashtext(...))`), hanya anggota group terpetakan (`memberOf`), upsert `auth_source='ad'` (+ `object_guid` bila AD), user keluar group → `is_active=false` + sesi dicabut, run `partial` tidak menonaktifkan massal (dibuktikan: bind service salah → `partial`, `deactivated=0`), riwayat `directory_sync_runs` + audit `ad.sync`; OpenLDAP overlay `memberof` diaktifkan untuk e2e
- [x] F5.6 **Login AD**: parser `DOMAIN\user` (netbios, case-insensitive) dan UPN (`user@fqdn`); username polos selalu lokal; `RANI_AD_ENABLED=1`; service bind → cari user (`sAMAccountName`, escape filter) → tolak disabled (`userAccountControl & 2`) → bind sebagai user → union role dari mapping → tanpa mapping ditolak `no_mapped_group`; JIT provisioning (`object_guid`, `upn`, `mail`, `displayName` disinkronkan); rate-limit per IP + principal `RANI_LOGIN_MAX_ATTEMPTS=20` per 5 menit (20 × 401 → 429); error generik + alasan internal di audit; tidak ada operasi tulis ke AD
- [x] F5.7 **Sesi & audit**: halaman sesi aktif (`/users/sessions`) — user, sumber `local`/`ad`, IP, dibuat, kedaluwarsa, tombol cabut (sid = 16 hex dari hash, tidak bocor token); revoke otomatis saat user dinonaktifkan / password direset / role berubah; audit `session.revoke` tercatat; filter audit log per `action`/`outcome`
- [ ] F5.8 **MFA & SSO** (fase lanjutan): TOTP untuk user lokal/AD, lalu SAML/OIDC; password login tetap tersedia kecuali site mewajibkan SSO

**Bukti implementasi F5 (2026-11-15, dev LXC ProjectDev):** migration `0006_users_ad` terpasang (`alembic_version=0006_users_ad`, round-trip downgrade/upgrade bersih); `admin` di-backfill ke role `admin`; `roles` = admin/operator/reader; resolver union + `normalize` unit test OK (`35 tests OK (4 skip)`); semua route `require_user(rank)`/`role_allows` dimigrasi ke `require_perm`. E2E OpenLDAP (container `osixia/openldap`, overlay `memberof`): **Test connection** hijau (4 user / 2 group); mapping `RANI-Admins→operator`, `RANI-Viewers→reader`; sync manual → `budi→operator`, `sari→reader`, `xdt` tidak terpetakan; login `CORP\budi`/`corp\budi` → 303 (`operator`), `CORP\xdt` → 401 `no_mapped_group`, password salah → 401; `budi` dikeluarkan dari group → sync → `is_active=false` + akses 401; group/bind rusak → `partial` + `deactivated=0`; 20×401 → 429; bind password write-only (0 kebocoran di HTML); guard seed admin 403, anti-lockout 409; `rani_report` SELECT tabel kredensial tetap `permission denied`. Commit `77ae0bd` (F5.1), `8e04b17` (F5.2/3/7), `0082187` (F5.4/5/6). Catatan lab: LDAPS berhasil di-*configure* dan TLS-verify berfungsi, tetapi build slapd 2.4.57 (bpo10, OpenSSL 1.1.1d) di container uji tidak dapat ber-handshake dengan OpenSSL 3 klien — bukti AD memakai `ldap://` (lab); di produksi AD/Windows LDAPS berjalan normal.

---
**Definition of Done per task:** ada bukti test nyata (curl output / screenshot / log), DB terisi benar, tidak ada regression di task sebelumnya.