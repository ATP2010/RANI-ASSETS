# Custom Reports (SQL read-only)

Menu **Reports** menyediakan report buatan user — mirip *Reports → Create New Report* di
Lansweeper Classic: tulis query SQL, **Save & Run**, lihat hasil sebagai grid dengan filter
per kolom, lalu ekspor CSV.

- URL: `http://192.168.88.92:8091/reports`
- Kode: `server/app/api/reports_ui.py` (halaman), `server/app/api/reports.py` (API run),
  `server/app/reporting.py` (guard + role read-only + eksekusi), `static/report.js` (grid).

## 1. Alur pakai

1. Login → menu **Reports** → daftar report tampil sebagai tabel — kotak **pencarian**
   di kiri atas men-filter langsung (nama/deskripsi/pemilik); kolom **Nama/Pemilik/Diubah**
   bisa diklik untuk sorting; **+ Buat report** di pojok kanan.
2. Klik **nama report** → halaman langsung menampilkan **hasil query** (auto-run):
   tabel filterable + info baris/ms + **Export CSV**. Tombol **Ubah query** memindah form
   edit, **Hapus report** menghapus (pemilik/admin). 
3. Di dalam halaman lihat: **Jalankan ulang** mengeksekusi ulang query yang tersimpan.
4. **+ Buat report**: isi **Nama**, **Deskripsi** (opsional), **SQL** (hanya
   `SELECT` / `WITH ... SELECT`). Panel kanan berisi contoh query yang bisa diklik.
5. **Simpan & Jalankan** → report tersimpan lalu query dieksekusi; halaman hasil langsung
   tampil. **Simpan** saja menyimpan tanpa menjalankan.

Tiga report contoh otomatis dibuat saat tabel masih kosong: *Aset per sistem operasi*,
*Top software (jumlah aset)*, *Aset tidak terlihat > 24 jam*.

## 1b. Custom dashboard (Setup → Dashboard)

Report bisa dijadikan **widget dashboard** di halaman utama (`/`):

1. Buat report dengan query yang menghasilkan **kategori → angka**
   (mis. `SELECT os_caption, count(*) AS aset FROM assets GROUP BY os_caption`).
2. Buka **Setup → Dashboard** → **Widget baru**: pilih **report sumber**, **jenis tampilan**
   (*Angka besar*, *Donut*, *Bar chart*, *Line chart*, *Tabel data*), **lebar** (¼ / ⅓ / ½ / penuh),
   **kolom kategori (x)** dan **kolom nilai (y)** (diambil dari pratinjau hasil report langsung
   di halaman form).
3. Simpan — widget muncul di beranda di bawah chart bawaan. Urutan bisa diubah (↑↓),
   lebar diganti, dimatikan sementara (tanpa dihapus), diduplikat, atau dihapus.
4. Widget yang laporannya dihapus menampilkan kartu error dengan tautan perbaikan.

Widget dieksekusi read-only seperti report (timeout, batas baris) dan hanya terlihat
untuk pemegang `dashboard.view` seperti dashboard biasa. Edit widget butuh permission
`setup.manage`.

## 2. Model keamanan (tiga lapis)

Query berasal dari user, jadi eksekusinya dibatasi berlapis:

| Lapis | Yang dilakukan | Efek |
|---|---|---|
| Role database terpisah `rani_report` | `GRANT SELECT` saja, `default_transaction_read_only=on`, `statement_timeout`, `search_path=rani_inventory` | Batas keras: `INSERT/UPDATE/DELETE/DDL` gagal di level Postgres walau guard aplikasi lolos |
| Guard aplikasi | hanya satu statement yang dimulai `SELECT`/`WITH`, tanpa `;` di tengah, tanpa kata kunci DML/DDL, tanpa fungsi berbahaya (`pg_sleep`, `pg_read_file`, `pg_ls_dir`, `dblink`, `lo_import`, ...) | Pesan error jelas sebelum query dikirim |
| Pembungkusan query | `SELECT * FROM (<sql>) q LIMIT max_rows + 1` | Hasil selalu terbatas; kelebihan 1 baris jadi penanda `truncated` |

Tambahan: tabel kredensial **tidak** bisa dibaca report — `app_users`, `auth_sessions`, dan
`enrollment_tokens` di-`REVOKE` dari role tersebut.

Yang tetap tidak bisa dicegah (dan bukan tujuan fitur ini): user dengan role `operator`/
`admin` bisa membaca seluruh data inventaris sesuai grant `SELECT` — itu memang wewenang
mereka. Report tidak memberi akses ke file server atau shell.

## 3. Tabel yang tersedia

`search_path` role = `rani_inventory, public`, jadi nama tabel bisa ditulis tanpa schema:

| Tabel | Isi |
|---|---|
| `assets` | satu baris per aset (hostname, os_caption, serial, primary_mac, status, first/last_seen, agent_id, attrs) |
| `software` | software per aset (`present` = masih terpasang) |
| `software_events` | riwayat install/uninstall/change |
| `software_reports` | payload push mentah (JSONB `raw`), status proses |
| `agents` | agent terdaftar (name, machine_id, last_seen, config) |
| `hw_components` | komponen hardware per aset |
| `users_seen` | user yang terlihat per aset |
| `security_state` | AV, firewall, BitLocker, TPM, Secure Boot, pending reboot |
| `network_interfaces` | interface per aset (MAC, IP, gateway, DNS) |
| `reports`, `audit_logs`, `scan_targets` | metadata aplikasi |

Kolom lengkap: `\d rani_inventory.assets` di psql, atau buka `server/app/models.py`.

## 4. Contoh query

```sql
-- Aset per OS
SELECT os_caption, count(*) AS aset
FROM assets
GROUP BY os_caption
ORDER BY aset DESC;

-- Top software (dipasang di berapa aset)
SELECT s.name_raw AS software, count(DISTINCT s.asset_id) AS aset
FROM software s
WHERE s.present
GROUP BY s.name_raw
ORDER BY aset DESC
LIMIT 20;

-- Software versi lama (contoh: Chrome < 120)
SELECT a.hostname, s.name_raw, s.version
FROM software s
JOIN assets a ON a.id = s.asset_id
WHERE s.present AND s.name_raw ILIKE 'Google Chrome%'
ORDER BY a.hostname;

-- Aset tanpa update security_state 7 hari
SELECT a.hostname, max(ss.checked_at) AS terakhir_cek
FROM assets a
LEFT JOIN security_state ss ON ss.asset_id = a.id
GROUP BY a.hostname
HAVING max(ss.checked_at) IS NULL OR max(ss.checked_at) < now() - interval '7 days'
ORDER BY terakhir_cek NULLS FIRST;
```

## 5. Batas & konfigurasi

| Env | Default | Arti |
|---|---|---|
| `RANI_REPORT_DB_USER` | `rani_report` | nama role read-only |
| `RANI_REPORT_DB_PASSWORD` | (wajib) | password role; kosong = menu Reports menolak eksekusi |
| `RANI_REPORT_MAX_ROWS` | `1000` | maksimum baris hasil (sisanya dipotong) |
| `RANI_REPORT_TIMEOUT_MS` | `8000` | statement timeout per query |

Role dibuat/diperbarui otomatis saat API start (advisory lock supaya dua worker uvicorn
tidak balapan). Ganti password: ubah `RANI_REPORT_DB_PASSWORD` di `.env` lalu restart api —
`ALTER ROLE ... PASSWORD` dijalankan ulang otomatis.

Query yang melebihi timeout dibatalkan Postgres dan pesannya muncul di UI, mis.
`query gagal: canceling statement due to statement timeout`. Error tersimpan di kolom
`reports.last_error` dan ditandai badge **error** di daftar report.

## 6. Hak akses

| Aksi | reader | operator | admin |
|---|---|---|---|
| Lihat report `shared` | ya | ya | ya |
| Lihat report `private` milik orang lain | tidak | tidak | ya |
| Jalankan / export CSV | ya | ya | ya |
| Buat report | tidak | ya | ya |
| Ubah/hapus report | tidak | hanya miliknya | semua |

Semua aksi tulis dan setiap eksekusi dicatat di `audit_logs`
(`report.create`, `report.save`, `report.delete`, `report.run` + durasi/baris/status).

## 7. Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET | `/reports` | daftar report |
| GET/POST | `/reports/new` | form report baru / simpan |
| GET | `/reports/{id}` | detail + editor (`?run=1` = auto-run) |
| POST | `/reports/{id}/save` | simpan perubahan (`action=run` untuk langsung eksekusi) |
| POST | `/reports/{id}/delete` | hapus (pemilik/admin) |
| POST | `/api/v1/reports/{id}/run` | eksekusi → JSON `{columns, rows, row_count, truncated, duration_ms}` |
| GET | `/reports/{id}/export.csv` | unduh hasil sebagai CSV |

## 8. Troubleshooting

| Gejala | Sebab / solusi |
|---|---|
| `fitur report belum aktif: set RANI_REPORT_DB_PASSWORD` | env belum diisi di `.env` lalu container belum di-restart |
| `permission denied for table ...` | nama tabel salah schema, atau tabel kredensial (memang diblokir). Pakai nama tabel tanpa schema |
| `hanya query SELECT atau WITH ... SELECT yang diizinkan` | query diawali kata lain (mis. `EXPLAIN`, `SHOW`) |
| `hanya satu statement; hapus ';' di tengah query` | ada `;` di tengah, termasuk di dalam string literal |
| `kata kunci terlarang: ...` | ada DML/DDL (insert/update/delete/create/...) walau di dalam komentar? komentar sudah diabaikan |
| `query gagal: canceling statement due to statement timeout` | query terlalu berat: tambahkan filter/indeks, atau naikkan `RANI_REPORT_TIMEOUT_MS` |
| Hasil terpotong di 1000 baris | naikkan `RANI_REPORT_MAX_ROWS`, atau persempit query |
| `permission denied for database` | role kehilangan `CONNECT` (mis. DB dibuat ulang) — restart api untuk provisioning ulang |

## 9. Checklist setelah menambah report

- [ ] `SELECT`/`WITH` saja, satu statement, tanpa `;` di tengah
- [ ] Kolom diberi alias yang enak dibaca (`AS aset`, bukan `count`)
- [ ] Ada `ORDER BY` + `LIMIT` untuk query yang bisa besar
- [ ] Coba **Simpan & Jalankan**, cek jumlah baris & waktu
- [ ] Cek filter per kolom + **Export CSV**
- [ ] Kalau report dipakai orang lain: beri deskripsi jelas (owner tetap bisa edit)