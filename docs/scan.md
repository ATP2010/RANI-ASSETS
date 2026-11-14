# Scan SNMP (grup IP + Custom OID)

Menu **Agents → Scan** memindai perangkat jaringan (switch, router, printer, AP) lewat SNMP,
mengikuti pola Lansweeper: *Scanning Targets* (range IP + kredensial) dan
*Custom OID Scanning* (OID tambahan per grup perangkat).

- Halaman: `http://192.168.88.92:8091/agents/scan`
- Kelola grup: `http://192.168.88.92:8091/agents/groups`
- Kode: `server/app/scanner.py` (mesin), `server/app/snmp.py` (klien SNMP stdlib),
  `server/app/api/scan.py` (API), `server/app/api/agents_ui.py` (halaman).

## 1. Konsep

| Istilah | Arti |
|---|---|
| **Grup IP** | Satu set range IP + kredensial SNMP (versi, community, port). Satu grup = satu target scan. |
| **Custom OID** | OID tambahan yang diambil dari perangkat, punya label; bisa difilter vendor/model. Berlaku untuk semua scan yang cocok filternya. |
| **Scan run** | Satu eksekusi scan: progres, hasil per IP, status (`running`/`done`/`cancelled`/`failed`). |
| **Asset network** | Perangkat yang menjawab SNMP dibuat/di-update sebagai asset `asset_type='network'` di halaman /assets. |

Data yang diambil otomatis dari setiap perangkat: `sysObjectID`, `sysDescr`, `sysName`,
`sysUpTime`, `ifNumber`, lalu entity MIB untuk serial/model/vendor
(`1.3.6.1.2.1.47.1.1.1.1.11` / `.2` / `.12`).

## 2. Menyiapkan grup IP

1. Buka **Agents → Grup IP & OID**.
2. Isi **Nama grup** (mis. `Switch Lantai 1`), **Deskripsi**, dan **Range IP** satu per baris:

   ```
   10.0.0.0/24
   10.0.1.5-10.0.1.20
   10.0.2.250
   ```

   Format yang diterima: CIDR, rentang `awal-akhir`, atau satu IP. **IPv4 saja.**
3. Pilih **SNMP** (`v2c` hampir selalu cukup), **Port** (161 default, ubah kalau perangkat
   memakai port non-standar), dan **Community** (mis. `public` atau string read-only khusus).
   Community disimpan terenkripsi (Fernet + `RANI_INGEST_PEPPER`).
4. **Tambah grup**. Range divalidasi saat disimpan; jumlah host dihitung otomatis
   (tanda `+` = melebihi batas per scan).
5. Grup bisa dinonaktifkan (toggle) tanpa dihapus, atau diubah lewat tombol **Ubah**
   (biarkan community kosong kalau tidak ingin menggantinya).

Batas: maksimum `RANI_SCAN_MAX_HOSTS` (default 512) host per scan, `RANI_SCAN_CONCURRENCY`
(16) probe paralel, timeout `RANI_SCAN_TIMEOUT_S` (1 dtk) per host. Range besar otomatis
dipotong dan ditandai `truncated` di ringkasan run.

## 3. Custom OID (contoh switch Cisco)

Buka bagian **Custom OID** di halaman yang sama, isi **Label**, **OID**, dan opsional
**Vendor/Model** (substring; kosong = semua perangkat).

| Label | OID | Catatan |
|---|---|---|
| Serial chassis | `1.3.6.1.2.1.47.1.1.1.1.11` | entity MIB, sudah diambil otomatis sebagai serial |
| Nama interface | `1.3.6.1.2.1.2.2.1.2.*` | akhiran `.*` = walk subtree (tabel) |
| Oper status interface | `1.3.6.1.2.1.2.2.1.8.*` | 1=up, 2=down, ... |
| Cisco CPU 5 detik | `1.3.6.1.4.1.9.2.1.56.0` | persen, khusus IOS |
| Cisco memory used | `1.3.6.1.4.1.9.2.1.8.0` | byte |
| Cisco serial | `1.3.6.1.4.1.9.3.6.3.0` | chassis serial khusus IOS |
| ARP table (IP→MAC) | `1.3.6.1.2.1.4.22.1.2.*` | walk, bisa besar — pakai filter vendor |
| Suhu | `1.3.6.1.4.1.9.9.13.1.3.1.3.*` | walk (Cisco envmon) |

Aturan:
- OID harus diawali `1.3.6`; akhiran `.*` berarti walk (maksimum 16 baris per OID).
- Filter **Vendor** dicocokkan sebagai substring ke vendor hasil deteksi
  (mis. `Cisco`), filter **Model** ke model hasil deteksi (mis. `C2960`).
- OID yang tidak ada di perangkat dilewati (atau dicatat `(error: ...)` bila gagal).
- Hapus OID lewat tombol **Hapus**; data yang sudah tersimpan di asset tidak ikut terhapus.

Data tersimpan per aset di `assets.attrs.snmp.oid_values` dengan key = label, dan bisa
diquery lewat menu **Reports**, mis.:

```sql
SELECT hostname, attrs -> 'snmp' -> 'oid_values' -> 'Cisco CPU 5 detik' AS cpu
FROM assets
WHERE asset_type = 'network'
ORDER BY hostname;
```

## 4. Menjalankan scan

1. **Agents → Scan**, pilih grup, klik **Mulai scan**.
2. Progres berjalan realtime (bar + `done/total` + jumlah ditemukan). Tombol
   **Batalkan** menghentikan scan setelah host yang sedang diproses selesai.
3. Hasil muncul per IP: status (`ok`/`timeout`/`error`), nama, vendor/model, serial,
   jumlah interface, dan nilai custom OID.
4. Setelah selesai, halaman menampilkan tautan **Buka hasil tersimpan**; riwayat 15 scan
   terakhir ada di tabel bawah dan bisa dibuka per run (`?run=<id>`).
5. Perangkat yang menjawab otomatis muncul di **/assets** (tipe `network`, badge online)
   dan bisa dibuka detailnya. Scan ulang memperbarui baris yang sama (identitas:
   serial → hostname → IP, hanya untuk asset network).

Scan berjalan sebagai background task di proses API (bukan di browser), jadi halaman boleh
ditutup. WebSocket memancarkan `scan.progress` dan `scan.done`; UI juga polling 1,2 dtk
sebagai fallback.

## 5. Yang perlu disiapkan di perangkat

- SNMP read-only aktif: pada Cisco `snmp-server community <RO> RO` + ACL ke IP server RANI.
- Versi 1/2c cukup; community hanya-baca (jangan pakai RW).
- UDP 161 (atau port grup) terbuka dari server RANI ke range target.
- Untuk data lengkap, MIB standar (`SNMPv2-MIB`, `IF-MIB`, `ENTITY-MIB`) sudah didukung
  perangkat; custom OID tidak butuh file MIB di server (cukup OID angka).

## 6. Batas & keamanan

- Hanya role `operator`/`admin` yang bisa membuat grup, mengubah, dan memulai scan;
  `reader` bisa melihat halaman, hasil, dan riwayat.
- Community tidak pernah ditampilkan lagi setelah disimpan (kolom password, tersimpan
  terenkripsi; dekripsi hanya saat scan).
- Scan hanya mengirim SNMP GET/GETNEXT (read-only). Tidak ada SET/write ke perangkat.
- Setiap start/cancel scan dicatat di `audit_logs` (`scan.start`, `scan.cancel`), perubahan
  grup/OID dicatat (`scan.group.save`, `scan.group.delete`, `scan.oid.create`, `scan.oid.delete`).

## 7. API

| Method | Path | Fungsi |
|---|---|---|
| POST | `/api/v1/scan/groups/{id}/run` | mulai scan (kembalikan `run_id`; `already_running` bila masih jalan) |
| GET | `/api/v1/scan/runs/{id}` | status + progres + hasil (maks 500 baris) |
| POST | `/api/v1/scan/runs/{id}/cancel` | set status `cancelled` |

## 8. Troubleshooting

| Gejala | Sebab / solusi |
|---|---|
| Semua host `timeout` | SNMP mati / community salah / ACL memblokir IP server / UDP port beda → cek di perangkat, coba `snmpget -v2c -c <community> <ip> 1.3.6.1.2.1.1.2.0` dari server |
| `timeout` hanya sebagian | range terlalu lebar untuk batas waktu; persempit atau naikkan `RANI_SCAN_TIMEOUT_S` |
| `error` dengan pesan `timeout menunggu balasan SNMP` | sama seperti di atas; perangkat lambat merespons |
| `tidak ada balasan SNMP` | perangkat menjawab tapi tanpa sysObjectID (bukan SNMP standar) |
| Data custom OID kosong | filter vendor/model tidak cocok, atau OID tidak ada. Cek vendor hasil scan (kolom Vendor) dan gunakan substring yang tepat |
| Walk `.*` hanya 16 baris | batas keamanan per OID; untuk tabel besar pakai Report SQL langsung |
| Hasil dipotong di 512 host | naikkan `RANI_SCAN_MAX_HOSTS` (ingat waktu & beban) atau pecah jadi beberapa grup |
| Chat/asset tidak muncul | perangkat menjawab tapi upsert gagal (cek log container `rani-inv-api-1`) |
| Scan tidak bisa dibatalkan | cancel berlaku setelah host yang sedang diproses selesai (timeout per host) |

## 9. Checklist pemakaian

- [ ] SNMP read-only aktif + ACL ke IP server
- [ ] Grup IP dibuat, range valid, community terisi, port benar
- [ ] Custom OID ditambahkan (opsional, dengan filter vendor kalau perlu)
- [ ] Scan dijalankan, semua host penting berstatus `ok`
- [ ] Asset network muncul di /assets dan detailnya terisi (serial, vendor, model, OID)
- [ ] Jadwalkan scan rutin: saat ini manual; untuk otomatis, tambahkan cron/worker nanti
      (belum ada scheduler scan di versi ini)

## Referensi

- Lansweeper Classic — *Scan extra SNMP data with custom OID scanning*:
  <https://docs.lansweeper.com/classic/docs/scan-extra-snmp-data-with-custom-oid-scanning>
- OID standar: `SNMPv2-MIB` (1.3.6.1.2.1.1), `IF-MIB` (1.3.6.1.2.1.2),
  `ENTITY-MIB` (1.3.6.1.2.1.47).