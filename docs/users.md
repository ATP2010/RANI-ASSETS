# Users & akses — lokal + Active Directory

> **Status: F5.1–F5.7 diimplementasikan (F5.8 MFA/SSO menyusul).** Migrasi
> `0006_users_ad` memperkenalkan role/permission custom; menu **Users**
> (`/users`) tersedia untuk pemegang permission terkait. Dokumen ini tetap
> menjadi acuan desain + operasi. Referensi: [Lansweeper — Restrict access to the web console](https://docs.lansweeper.com/classic/docs/restrict-access-to-the-web-console),
> [Active Directory Connector](https://docs.lansweeper.com/docs/active-directory-connector),
> [Authentication (SSO/MFA)](https://docs.lansweeper.com/docs/authentication).

Menu **Users** mengelola **akun yang bisa login ke RANI** — bukan user hasil scan.
User yang ditemukan di komputer/AD tetap menjadi data aset (tab **Users** di detail
asset) dan tidak otomatis mendapat akses.

Dua metode login yang didukung:

| Metode | Username | Password disimpan | Cocok untuk |
|---|---|---|---|
| **Lokal** | `admin`, `operator1` (tanpa `\` atau `@`) | hash bcrypt di `app_users` | admin break-glass, akun teknis, lab |
| **Active Directory** | `DOMAIN\user` atau `user@domain.local` | **tidak pernah disimpan**; diverifikasi bind LDAP | organisasi dengan AD |

AD user **tidak** bisa login dengan username polos, dan user lokal tidak bisa login
memakai prefix domain. Dengan aturan ini tidak ada bentrok nama antara kedua sumber.

---

## 1. Peta menu

Menu **Users** hanya terlihat untuk pemegang permission `users.view` (default: role
admin). Submenu direncanakan:

| Halaman | Path | Isi | Permission |
|---|---|---|---|
| Daftar user | `/users` | semua akun (lokal + AD), status, role, login terakhir; tambah/ubah/nonaktifkan/reset password | `users.view` / `users.manage` |
| Role & akses | `/users/roles` | daftar role, matriks permission, buat/duplikat/hapus role custom | `roles.view` / `roles.manage` |
| Direktori (AD) | `/users/directory` | connector LDAP/LDAPS, test koneksi, mapping group → role, tombol sync + riwayat | `directory.view` / `directory.manage` / `directory.sync` |
| Sesi & audit | `/users/sessions` | sesi aktif (user, IP, waktu), cabut sesi; audit login/perubahan akses | `audit.view` |

Submenu baru bisa ditambahkan tanpa mengubah top-level **Users**.

---

## 2. Role & permission

Satu user boleh punya **beberapa role**. Permission efektif = **union** dari semua
role (yang paling permisif menang). Role yang sama juga bisa diberikan ke banyak user
dan ke group AD.

### 2.1 Katalog permission

Format `modul.aksi`. Action `view` untuk melihat, `manage` untuk mengubah konfigurasi,
`run` untuk menjalankan operasi, `export` untuk mengunduh data.

| Modul | Permission | Arti |
|---|---|---|
| Dashboard | `dashboard.view` | melihat dashboard dan statistik |
| Assets | `assets.view` | daftar/detail asset |
| | `assets.export` | export CSV asset |
| Reports | `reports.view` | melihat daftar/hasil report |
| | `reports.run` | menjalankan report |
| | `reports.export` | export CSV hasil report |
| | `reports.manage` | membuat/mengubah/menghapus report |
| Scan | `scan.view` | melihat grup, riwayat, dan hasil scan |
| | `scan.run` | memulai/membatalkan scan |
| | `scan.manage` | CRUD grup IP, custom OID, toggle FDB |
| Port map | `portmap.view` | halaman port map dan lookup MAC |
| Agents | `agents.view` | halaman agent + unduhan |
| | `agents.manage` | enrollment token, revoke agent |
| Users | `users.view` | daftar user dan sesi |
| | `users.manage` | tambah/ubah/nonaktifkan user, reset password, cabut sesi |
| Roles | `roles.view` | daftar role |
| | `roles.manage` | buat/ubah/hapus role dan permission |
| Directory | `directory.view` | connector AD + riwayat sync |
| | `directory.manage` | ubah connector, test koneksi, mapping group |
| | `directory.sync` | jalankan sync manual |
| Audit | `audit.view` | halaman sesi & audit |

### 2.2 Default role bawaan

| Permission | reader | operator | admin |
|---|:--:|:--:|:--:|
| `dashboard.view` | ✓ | ✓ | ✓ |
| `assets.view` / `assets.export` | ✓ / ✓ | ✓ / ✓ | ✓ |
| `reports.view` / `reports.run` / `reports.export` | ✓ / ✓ / ✓ | ✓ | ✓ |
| `reports.manage` | — | ✓ | ✓ |
| `scan.view` | ✓ | ✓ | ✓ |
| `scan.run` / `scan.manage` | — | ✓ / ✓ | ✓ |
| `portmap.view` | ✓ | ✓ | ✓ |
| `agents.view` | ✓ | ✓ | ✓ |
| `agents.manage` | — | ✓ | ✓ |
| `users.*` / `roles.*` / `directory.*` / `audit.view` | — | — | ✓ |

`admin` adalah role **terkunci**: selalu punya semua permission, tidak bisa dihapus,
tidak bisa diubah lewat UI. Tujuannya menjamin selalu ada jalan masuk.

### 2.3 Role custom

- Dibuat dari halaman **Role & akses** dengan nama unik + deskripsi + checkbox permission.
- Bisa **duplikat** role yang ada sebagai titik awal.
- Role custom tidak punya "rank" — yang berlaku hanya himpunan permission.
- Tidak bisa dihapus selama masih dipakai user atau mapping group AD.
- Perubahan permission pada role langsung berlaku pada request berikutnya (permission dibaca dari DB); perubahan role seorang user mencabut sesi user itu agar tidak memakai hak lama.
- Guard anti-lockout: sistem menolak aksi yang membuat tidak ada lagi user aktif dengan
  `users.manage` + `roles.manage` (admin terakhir tidak bisa dinonaktifkan/diturunkan).

---

## 3. User lokal

Akun dibuat manual oleh pemegang `users.manage`.

| Field | Aturan |
|---|---|
| `username` | wajib, unik, 3–64 karakter, **tidak boleh mengandung `\` atau `@`** (direservasi untuk AD) |
| `display_name` | opsional |
| `email` | opsional, untuk identifikasi |
| `password` | minimal 12 karakter (dapat diatur), bcrypt cost 12 |
| `roles` | satu atau lebih role |
| `is_active` | nonaktif = tidak bisa login, sesi dicabut |

Aksi yang didukung:

- **Tambah user** — password diisi admin; opsi "wajib ganti password saat login pertama"
  disiapkan sebagai fase lanjutan.
- **Reset password** — admin memasukkan password baru; semua sesi user dicabut, audit
  `user.password_reset`.
- **Nonaktifkan / aktifkan** — soft disable (`is_active=false`); data audit dan riwayat
  login tetap ada.
- **Hapus** — hanya untuk akun yang tidak punya jejak audit penting; defaultnya
  nonaktifkan. Akun AD yang dihapus dari direktori juga hanya dinonaktifkan.
- **Cabut sesi** — semua sesi atau sesi tertentu dari halaman Sesi & audit.

Aturan tambahan:

- Admin yang di-seed dari `RANI_ADMIN_USER` tidak bisa dihapus/nonaktifkan lewat UI.
- User lokal terakhir yang aktif dengan permission `users.manage` dilindungi guard.
- Perubahan role langsung menulis audit `user.role_change` dan mencabut sesi user.

---

## 4. Active Directory (LDAP/LDAPS)

RANI hanya **membaca** AD: bind sebagai service account, mencari user/group, lalu bind
sebagai user untuk memverifikasi password. Tidak ada operasi Add/Update/Delete ke AD.

### 4.1 Prasyarat

- Service account AD dengan hak **read-only** pada base DN (mis. `svc-rani@corp.local`).
- LDAPS (`ldaps://…:636`) atau StartTLS; sertifikat CA internal disiapkan (PEM).
- Base DN user dan group, mis. `OU=Users,DC=corp,DC=local`,
  `OU=Groups,DC=corp,DC=local`.
- Group AD yang akan dipetakan ke role, mis. `RANI-Admins`, `RANI-Operators`,
  `RANI-Viewers`.
- Jam server sinkron (selisih waktu dapat menggagalkan bind/Kerberos; untuk LDAP simple
  bind biasanya tidak, tetapi tetap disarankan).

### 4.2 Connector

Satu connector = satu domain. Multi-domain/forest = beberapa connector.

| Field | Contoh | Catatan |
|---|---|---|
| Nama | `AD Corp` | label di UI |
| Domain NetBIOS | `CORP` | dipakai mencocokkan `CORP\user` |
| Domain FQDN | `corp.local` | dipakai mencocokkan `user@corp.local` |
| URL | `ldaps://dc01.corp.local:636` | `ldap://` hanya untuk lab |
| Gunakan LDAPS | ✓ | wajib untuk produksi |
| Verifikasi sertifikat | ✓ | matikan hanya untuk uji dengan self-signed |
| CA certificate | `-----BEGIN CERTIFICATE-----…` | opsional bila CA sudah dipercaya OS |
| Bind DN | `CN=svc-rani,OU=Service,DC=corp,DC=local` | service account |
| Bind password | •••••••• | terenkripsi Fernet, write-only |
| Base DN user | `OU=Users,DC=corp,DC=local` | awal pencarian user |
| User filter | `(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))` | default menolak akun disabled |
| Group filter | `(objectClass=group)` | untuk browse group |
| Nested groups | ✓/— | resolusi `memberOf` berantai |
| Interval sync | `3600` detik | 0 = hanya manual |

Tombol **Test connection** melakukan: connect → bind service → baca `rootDSE` →
hitung user/grup di base DN. Hasil dan error ditampilkan tanpa membocorkan password.

### 4.3 Mapping group → role

- Halaman **Direktori (AD)** → daftar group (browse dari AD atau input DN manual).
- Setiap group dipetakan ke satu role (bawaan atau custom).
- User yang menjadi anggota beberapa group mendapat **union** role.
- Group yang tidak dipetakan **tidak** memberi akses. User yang hanya ada di group tak
  terpetakan tidak bisa login (`no_mapped_group`).
- Nested group: bila aktif, keanggotaan di sub-group ikut dihitung (AD matching rule
  `1.2.840.113556.1.4.1941`). Bila tidak, hanya anggota langsung.
- Konektor membaca atribut yang ada di skema server (deteksi via `cn=subschema`),
  sehingga AD dan OpenLDAP sama-sama bisa dipakai. `objectGUID`/`userAccountControl`/
  `userPrincipalName` hanya ada di AD; di OpenLDAP, user dikenali dari
  `sAMAccountName` dan status disabled tidak dibaca (filter `user_filter` bisa dipakai
  untuk mengecualikan akun).
- Pada AD, `memberOf` adalah backlink sehingga selalu mutakhir. Pada OpenLDAP, overlay
  `memberof` harus diaktifkan agar pencarian `memberOf=<dn group>` bekerja
  (`olcMemberOfGroupOC: groupOfNames`, `olcMemberOfMemberAD: member`).

### 4.4 Sync

Sync menarik **hanya user yang menjadi anggota group terpetakan** (bukan seluruh base
DN), sehingga data yang disimpan minimal dan akses jelas.

Setiap run:

1. Ambil daftar group aktif + role-nya.
2. Cari anggota tiap group (range retrieval untuk group > 1500 anggota).
3. Upsert `app_users` dengan `auth_source='ad'`, `username='corp\sam'`, `object_guid`,
   `upn`, `email`, `display_name`.
4. Hitung union role; tulis `app_user_roles`. Untuk user AD, role adalah **murni
   hasil mapping** (replace, bukan merge) — tambahkan permission lewat mapping group,
   bukan lewat halaman user, karena perubahan manual akan tertimpa sync berikutnya.
5. User AD yang **tidak lagi** ada di group terpetakan → `is_active=false`.
6. Simpan ringkasan di `directory_sync_runs`.
7. Audit `ad.sync` (jumlah created/updated/deactivated/roles_changed, durasi, error).

Aturan penting:

- **Tidak** menyentuh akun lokal, admin seed, atau akun AD dari connector lain.
- Sync bersifat delta: user baru dibuat, user lama diperbarui, user hilang dinonaktifkan
  (tidak dihapus) supaya audit tetap utuh.
- Bila satu group gagal dibaca, run ditandai `partial`; **tidak** ada deaktivasi massal.
  Data run terakhir yang sukses tetap dipakai.
- Dua sync tidak boleh berjalan bersamaan (advisory lock per connector).
- Sync manual dan terjadwal memakai jalur kode yang sama; hasilnya bisa dilihat di
  riwayat sync (status, durasi, jumlah user, error).

### 4.5 Login AD

1. User membuka `/login` dan mengetik `CORP\budi` (atau `budi@corp.local`).
2. RANI memilih connector berdasarkan NetBIOS/FQDN.
3. Service bind → cari user dengan `sAMAccountName=budi` di base DN + user filter.
4. Tolak bila akun AD disabled/locked/expired.
5. Bind sebagai DN user dengan password yang diketik (password tidak disimpan).
6. Ambil group user; hitung union role dari mapping.
7. Tidak ada role terpetakan → tolak (`no_mapped_group`), audit kegagalan.
8. Upsert akun AD (JIT provisioning) + role, lalu buat sesi seperti login lokal.

Username yang disimpan = `corp\budi` (lowercase). Login berikutnya memperbarui
`last_login_at` dan `last_sync_at`.

---

## 5. Login, sesi, dan audit

### 5.1 Routing input login

| Input | Metode | Connector |
|---|---|---|
| `admin` | lokal | — |
| `DOMAIN\user` | AD | cocokkan NetBIOS `DOMAIN` |
| `user@corp.local` | AD | cocokkan FQDN `corp.local` |
| `user@domain-lain` | AD | connector lain (bila ada) |

Username polos **selalu** lokal; tidak ada fallback otomatis ke AD. Ini mencegah user
lokal "terbajak" oleh akun AD bernama sama.

### 5.2 Rate-limit & error

- Rate-limit per IP **dan** per principal (default 20 percobaan / 5 menit).
- Pesan error selalu generik: "username/password salah" — tidak membedakan user tidak
  ada, password salah, atau tidak punya group.
- Audit mencatat alasan internal (`bad_password`, `not_found`, `no_mapped_group`,
  `ad_unreachable`, `disabled`) untuk admin, bukan untuk penyerang.

### 5.3 Sesi

- Cookie `rani_session` (HttpOnly, SameSite=Lax) + baris `auth_sessions` (hash token).
- TTL dari `RANI_SESSION_TTL_H` (default 12 jam).
- Sesi dicabut saat: logout, user dinonaktifkan, password direset, role berubah,
  sync menonaktifkan akun, atau admin menekan **Cabut sesi**.
- Halaman **Sesi & audit** menampilkan user, sumber (`local`/`ad`), IP, waktu dibuat,
  waktu kedaluwarsa, dan tombol cabut.

### 5.4 Audit

Event yang dicatat di `audit_logs`:

`login` (outcome success/failure + source), `logout`, `user.create`, `user.update`,
`user.disable`, `user.enable`, `user.password_reset`, `user.role_change`,
`role.create`, `role.update`, `role.delete`, `ad.connector.create`,
`ad.connector.update`, `ad.connector.test`, `ad.sync`, `session.revoke`.

Password, bind password, dan token tidak pernah masuk audit/log.

---

## 6. Keamanan

- **Bind password** disimpan terenkripsi (Fernet, kunci dari `RANI_INGEST_PEPPER`),
  hanya bisa ditulis, tidak pernah dikembalikan API/UI. Mengubah pepper = password
  connector harus diisi ulang.
- **LDAPS wajib** untuk produksi. `ldap://` hanya untuk lab; UI menampilkan peringatan.
- **Service account read-only**; RANI tidak pernah mengirim Add/Modify/Delete ke AD.
- **Local break-glass admin** selalu tersedia; sync AD tidak boleh menonaktifkannya.
- **Least privilege**: permission default `reader`; akses admin hanya lewat role admin
  atau role custom yang jelas.
- **Anti-lockout**: minimal satu user aktif harus punya `users.manage` + `roles.manage`.
- **Privilege escalation**: hanya pemegang `roles.manage` yang bisa mengubah role;
  role admin tidak bisa diubah.
- **MFA & SSO** (TOTP, SAML, OIDC) belum termasuk fase ini — lihat roadmap.

---

## 7. API

| Method | Path | Fungsi |
|---|---|---|
| GET | `/api/v1/users` | daftar user (filter sumber/status/role, cari) |
| POST | `/api/v1/users` | buat user lokal |
| PATCH | `/api/v1/users/{id}` | ubah display/email/role/status |
| POST | `/api/v1/users/{id}/password` | reset password (lokal) |
| POST | `/api/v1/users/{id}/revoke-sessions` | cabut semua sesi user |
| GET | `/api/v1/roles` | daftar role + permission |
| POST/PATCH/DELETE | `/api/v1/roles[/{id}]` | kelola role custom |
| GET | `/api/v1/permissions` | katalog permission untuk UI |
| GET/POST/PATCH/DELETE | `/api/v1/directory/connectors[/{id}]` | connector AD |
| POST | `/api/v1/directory/connectors/{id}/test` | test bind + hitung user/group |
| GET | `/api/v1/directory/connectors/{id}/groups?q=` | browse group AD |
| GET/POST/PATCH/DELETE | `/api/v1/directory/group-roles[/{id}]` | mapping group → role |
| POST | `/api/v1/directory/connectors/{id}/sync` | sync manual |
| GET | `/api/v1/directory/connectors/{id}/sync-runs` | riwayat sync |
| GET | `/api/v1/sessions` | sesi aktif |
| POST | `/api/v1/sessions/{id}/revoke` | cabut sesi |

Semua endpoint memakai dependency permission (`require_perm("users.manage")`), bukan
lagi perbandingan rank role.

---

## 8. Skema DB (migration `0006_users_ad`)

```
roles(id, slug UNIQUE, name, description, permissions JSONB, is_builtin, created_at, updated_at)
app_user_roles(user_id, role_id)                       -- PK gabungan
app_users(+ auth_source, domain, sam_account_name, upn, object_guid,
           email, last_sync_at, updated_at)            -- password_hash NULL untuk AD
auth_sessions(+ auth_source)
directory_connectors(id, name, domain, domain_fqdn, url, use_ldaps, tls_verify,
                     ca_cert_pem, bind_dn, bind_password_enc, base_dn,
                     user_filter, group_filter, nested_groups, sync_interval_s,
                     enabled, last_sync_at, last_sync_status, last_sync_error)
directory_group_roles(id, connector_id, group_dn, group_name, role_id, enabled)
directory_sync_runs(id, connector_id, mode, status, users_seen, created, updated,
                    deactivated, roles_changed, error, started_at, finished_at)
```

Migrasi mem-backfill `app_users.role` lama ke `app_user_roles` (reader/operator/admin)
sebelum kolom string dihapus. Seed role bawaan harus idempotent.

---

## 9. Environment

| Variable | Default | Status | Arti |
|---|---|---|---|
| `RANI_SESSION_TTL_H` | `12` | aktif | umur sesi login (jam) |
| `RANI_AUTH_LOCAL_ENABLED` | `1` | aktif | izinkan login lokal |
| `RANI_AD_ENABLED` | `0` | aktif | saklar global login AD |
| `RANI_AD_SYNC_INTERVAL_S` | `3600` | aktif | interval default untuk connector baru (0 = manual) |
| `RANI_PASSWORD_MIN_LEN` | `12` | aktif | panjang minimum password lokal |
| `RANI_LOGIN_MAX_ATTEMPTS` | `20` | aktif | percobaan per IP/principal per 5 menit |

Bind password **tidak** diletakkan di `.env`; diisi lewat UI dan disimpan terenkripsi
di DB. Variabel `RANI_INGEST_PEPPER` wajib sudah diatur sebelum menyimpan connector.
Jangan mematikan `RANI_AUTH_LOCAL_ENABLED` sebelum ada minimal satu group AD yang
dipetakan ke role admin — akun lokal adalah jalan masuk darurat.

---

## 10. Troubleshooting

| Gejala | Sebab / solusi |
|---|---|
| `invalid attribute type objectGUID` saat sync (OpenLDAP) | Atribut khusus AD tidak ada; konektor otomatis menyesuaikan via skema (`subschemaSubentry`). Bukan error di AD. |
| Sync selalu `partial` | Bind service gagal / group tidak terbaca; `directory_sync_runs` menampilkan error per group. Perbaiki lalu sync ulang — run partial tidak menonaktifkan user. |
| Group AD kosong tidak error tapi sync `success` 0 user | Filter/member salah; cek `memberOf` (AD: backlink otomatis; OpenLDAP: aktifkan overlay `memberof` — lihat `docs/users.md` §4.4) |
| Login AD gagal padahal password benar | Akun di luar group terpetakan (`no_mapped_group`), disabled di AD, atau connector disabled; cek audit `reason`. |
| `Test connection` gagal `invalid credentials` | bind DN/password salah, atau akun service terkunci. Coba `ldapsearch -H ldaps://… -D "<bind DN>" -W -b "<base DN>"` dari server |
| Gagal TLS `certificate verify failed` | CA internal belum diunggah; unggah CA PEM atau (hanya lab) matikan verifikasi |
| Login AD selalu `username/password salah` | pastikan memakai `DOMAIN\user`/UPN, bukan username polos; cek connector domain cocok |
| Login AD gagal `no_mapped_group` | user tidak ada di group yang dipetakan; tambahkan mapping atau masukkan user ke group |
| Sync 0 user | base DN/filter salah, group kosong, atau service account tidak boleh membaca group. Cek riwayat sync |
| Group besar tidak tersinkron | range retrieval gagal atau group > batas; cek log connector, naikkan timeout LDAP |
| User AD tidak nonaktif setelah keluar group | run terakhir `partial`/gagal; perbaiki error lalu sync ulang. Deaktivasi tidak dilakukan pada run parsial |
| User lokal tidak bisa login setelah AD aktif | pastikan username polos (tanpa `\`/`@`); cek `is_active` dan rate-limit |
| Semua admin terkunci | gunakan akun break-glass dari `RANI_ADMIN_USER`, atau reset lewat CLI/DB sesuai prosedur darurat |
| Perubahan role belum berlaku | sesi lama masih aktif; cabut sesi user atau tunggu TTL |

---

## 11. Checklist setup

- [ ] Tentukan sumber akun: lokal saja, AD saja, atau keduanya
- [ ] Buat service account AD read-only + siapkan CA/LDAPS
- [ ] Login sebagai admin, buka **Users → Direktori (AD)**, isi connector
- [ ] **Test connection** hijau (bind + hitung user/group)
- [ ] Buat/pilih role (bawaan atau custom) dan permission-nya
- [ ] Petakan group AD → role; pastikan minimal satu group admin
- [ ] Jalankan **Sync now**, cek ringkasan (created/updated/deactivated)
- [ ] Login dengan `DOMAIN\user`; pastikan role dan menu sesuai
- [ ] Uji negatif: user di luar group ditolak, password salah ditolak, akun disabled ditolak
- [ ] Nonaktifkan satu user di AD, sync ulang, pastikan akun RANI nonaktif dan sesinya dicabut
- [ ] Pastikan akun lokal break-glass masih bisa login
- [ ] Catat interval sync dan pemilik service account

---

## 12. Roadmap

1. **F5.1** ✅ skema role/permission + seed + backfill + permission resolver.
2. **F5.2** ✅ halaman Users + CRUD lokal + reset password + guard admin terakhir.
3. **F5.3** ✅ halaman Role & akses + role custom + matriks permission.
4. **F5.4** ✅ connector AD + enkripsi bind password + test/bind + browse group.
5. **F5.5** ✅ mapping group → role + sync manual/terjadwal + riwayat sync.
6. **F5.6** ✅ login AD (`DOMAIN\user`) + JIT provisioning + deny unmapped.
7. **F5.7** ✅ halaman Sesi & audit.
8. **F5.8** MFA TOTP dan SSO SAML/OIDC (fase lanjutan, belum dijadwalkan).
