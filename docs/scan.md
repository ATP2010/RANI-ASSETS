# Scan SNMP (grup IP + Custom OID)

Menu **Agents → Scan** memindai perangkat jaringan (switch, router, printer, AP) lewat SNMP,
mengikuti pola Lansweeper: *Scanning Targets* (range IP + kredensial) dan
*Custom OID Scanning* (OID tambahan per grup perangkat). Untuk switch, hasil scan juga
mengisi **port map Layer-2** (MAC ↔ port) di menu **Agents → Port map**.

- Halaman: `http://192.168.88.92:8091/agents/scan`
- Port map L2: `http://192.168.88.92:8091/agents/portmap`
- Kelola grup: `http://192.168.88.92:8091/agents/groups`
- Kode: `server/app/scanner.py` (mesin), `server/app/snmp.py` (klien SNMP stdlib),
  `server/app/api/scan.py` + `server/app/api/network.py` (API),
  `server/app/api/agents_ui.py` (halaman).

## 1. Konsep

| Istilah | Arti |
|---|---|
| **Grup IP** | Satu set range IP + kredensial SNMP (versi, community, port). Satu grup = satu target scan. |
| **Custom OID** | OID tambahan yang diambil dari perangkat, punya label; bisa difilter vendor/model. Berlaku untuk semua scan yang cocok filternya. |
| **Scan run** | Satu eksekusi scan: progres, hasil per IP, status (`running`/`done`/`cancelled`/`failed`). |
| **Asset network** | Perangkat yang menjawab SNMP dibuat/di-update sebagai asset `asset_type='network'` di halaman /assets. |
| **Port map** | Tabel MAC ↔ port switch (`endpoint_port_mappings`) dari tabel forwarding bridge: perangkat apa nyangkut di port mana. |

Data yang diambil otomatis dari setiap perangkat: `sysObjectID`, `sysDescr`, `sysName`,
`sysUpTime`, `ifNumber`, lalu entity MIB untuk serial/model/vendor
(`1.3.6.1.2.1.47.1.1.1.1.11` / `.2` / `.12`). Untuk switch ditambah tabel forwarding
(bridge FDB) → port map.

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

## 3b. Port map Layer-2 (MAC ↔ port switch)

Untuk perangkat yang punya tabel forwarding (switch), scan juga mengambil **FDB bridge**:
MAC mana dipelajari di port mana. Hasilnya masuk tabel `endpoint_port_mappings` dan bisa
dilihat di **Agents → Port map** atau tab **Port map** pada detail asset network.

| Data | OID | Arti |
|---|---|---|
| `dot1dTpFdbPort` | `1.3.6.1.2.1.17.4.3.1.2` | MAC → nomor bridge port (BRIDGE-MIB) |
| `dot1dTpFdbStatus` | `1.3.6.1.2.1.17.4.3.1.3` | `learned` / `self` / `mgmt` / `static` |
| `dot1dBasePortIfIndex` | `1.3.6.1.2.1.17.1.4.1.2` | bridge port → ifIndex |
| `ifName` / `ifDescr` | `1.3.6.1.2.1.31.1.1.1.1` / `1.3.6.1.2.1.2.2.1.2` | ifIndex → nama port |
| `dot1qTpFdbPort` | `1.3.6.1.2.1.17.7.1.2.2.1.2` | versi VLAN-aware (Q-BRIDGE-MIB) |
| `dot1qVlanFdbId` | `1.3.6.1.2.1.17.7.1.4.2.1.3` | fdb-id → VLAN |

Cara kerjanya:

1. Scanner mencoba **dot1d** dulu (paling universal). Kalau kosong, pakai **dot1q**
   (switch VLAN-aware sering hanya mengisi tabel ini).
2. MAC diambil dari **indeks OID** (6 oktet desimal), jadi tidak terpengaruh decoding
   OCTET STRING. MAC multicast/broadcast dibuang.
3. Walk memakai **GETBULK** (SNMPv2c) supaya tabel berisi ribuan MAC tetap cepat; v1
   otomatis fallback ke GETNEXT.
4. MAC yang sudah dikenal sebagai asset (cocok `assets.primary_mac`) otomatis ditautkan
   ke asset itu. **MAC tak dikenal tidak dibuatkan asset baru** — FDB hanya bukti
   keberadaan di port, bukan identitas lengkap.
5. Scan berikutnya memperbarui baris yang sama; MAC yang hilang ditandai
   `present=false` (riwayat tetap, bisa ditampilkan dengan centang *termasuk MAC hilang*).

Batas & konfigurasi:

| Env | Default | Arti |
|---|---|---|
| `RANI_SCAN_FDB_ENABLED` | `1` | saklar global port map |
| `RANI_SCAN_FDB_MAX` | `2000` | maksimum MAC per perangkat per scan; lebih = `truncated` |
| `RANI_SCAN_FDB_UPLINK_MACS` | `10` | port dengan ≥ N MAC diberi badge **uplink?** |

Port map bisa dimatikan **per grup** (checkbox *Kumpulkan port map* di form grup IP) untuk
perangkat lama yang lambat atau bila topologi tidak diperlukan.

Membaca hasilnya:

- Satu baris = satu MAC terlihat di satu port switch. MAC sama boleh muncul di beberapa
  switch (roaming/stack/uplink).
- Badge **uplink?** menandai port yang mempelajari banyak MAC (biasanya port trunk/uplink
  ke switch lain). MAC di belakang port itu bukan perangkat yang menempel langsung.
- Status `self` biasanya MAC milik switch itu sendiri (CPU/management interface).
- VLAN `—` berarti perangkat hanya mengisi dot1d (tanpa info VLAN); `0` = tidak diketahui.

Query SQL (menu **Reports**) untuk port map:

```sql
SELECT s.hostname AS switch, m.if_name AS port, m.vlan, m.mac,
       e.hostname AS endpoint, m.last_seen
FROM endpoint_port_mappings m
JOIN assets s ON s.id = m.switch_asset_id
LEFT JOIN assets e ON e.id = m.endpoint_asset_id
WHERE m.present
ORDER BY s.hostname, m.if_name, m.mac;
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
6. Untuk switch, kolom **Port map** di hasil scan menunjukkan jumlah MAC yang masuk
   `endpoint_port_mappings`. Buka **Agents → Port map** (atau tab *Port map* di detail
   asset) untuk melihat MAC ↔ port.

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
- Scan hanya mengirim SNMP GET/GETNEXT/GETBULK (read-only). Tidak ada SET/write ke perangkat.
- Port map menyimpan **ringkasan** FDB di `assets.attrs.snmp.bridge` (jenis tabel, jumlah,
  status) dan detail MAC↔port di `endpoint_port_mappings`; tabel FDB mentah tidak
  dimasukkan ke JSONB supaya `assets.attrs` tidak membengkak.
- MAC dari FDB **tidak** membuat asset baru — hanya ditautkan bila cocok `primary_mac`.
- Setiap start/cancel scan dicatat di `audit_logs` (`scan.start`, `scan.cancel`), perubahan
  grup/OID dicatat (`scan.group.save`, `scan.group.delete`, `scan.oid.create`, `scan.oid.delete`).

## 7. API

| Method | Path | Fungsi |
|---|---|---|
| POST | `/api/v1/scan/groups/{id}/run` | mulai scan (kembalikan `run_id`; `already_running` bila masih jalan) |
| GET | `/api/v1/scan/runs/{id}` | status + progres + hasil (maks 500 baris) |
| POST | `/api/v1/scan/runs/{id}/cancel` | set status `cancelled` |
| GET | `/api/v1/network/port-map` | ringkasan per switch + baris MAC↔port. Query: `switch=<uuid>`, `q=<teks>`, `present=true|false`, `limit` (≤5000) |
| GET | `/api/v1/network/lookup` | cari MAC / hostname / nama port: `q=` (min 2 karakter), hasil maks 200 baris |

Contoh:

```
GET /api/v1/network/port-map?switch=c24f264e-c572-46fa-ab0c-3910acb890cb
GET /api/v1/network/lookup?q=bc:24:11:e9
```

Respons `port-map` berisi `summary[]` (per switch: `hostname`, `ip`, `macs`, `ports`,
`known`, `last_seen`) dan `rows[]` (`mac`, `vlan`, `port`, `if_index`, `bridge_port`,
`status`, `present`, `endpoint_asset_id`, `endpoint_hostname`, `first_seen`, `last_seen`).

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
| Port map kosong padahal switch menjawab | (1) grup punya *Kumpulkan port map* nonaktif / `RANI_SCAN_FDB_ENABLED=0`; (2) perangkat bukan switch (tidak punya BRIDGE-MIB); (3) FDB memang belum terisi lalu lintas. Cek `attrs.snmp.bridge.kind` di detail asset network |
| `attrs.snmp.bridge.error` berisi timeout | walk FDB lebih berat dari GET biasa; naikkan `RANI_SCAN_TIMEOUT_S` atau turunkan `RANI_SCAN_FDB_MAX`. Port map gagal **tidak** menggagalkan scan: data SNMP lain tetap tersimpan |
| MAC aktif jauh lebih sedikit dari jumlah kabel | tabel FDB hanya berisi MAC yang baru mengirim trafik (aging). Jalankan scan saat jam kerja atau setelah trafik lewat |
| Ada badge `uplink?` di banyak port | `RANI_SCAN_FDB_UPLINK_MACS` terlalu kecil atau switch punya banyak port trunk; badge hanya petunjuk, bukan data salah |
| `truncated` di status port map | tabel melebihi `RANI_SCAN_FDB_MAX` (default 2000). Naikkan bila perlu; sisa MAC tidak terbaca pada scan itu |
| Endpoint tidak tertaut padahal ada di halaman | MAC di FDB tidak sama dengan `assets.primary_mac` (mis. Wi-Fi privat / MAC virtual). Port map tidak membuat asset baru |
| VLAN selalu `—` | perangkat hanya mengisi dot1d (tanpa VLAN); Q-BRIDGE-MIB (`dot1qVlanFdbId`) tidak tersedia |

## 9. Checklist pemakaian

- [ ] SNMP read-only aktif + ACL ke IP server
- [ ] Grup IP dibuat, range valid, community terisi, port benar
- [ ] Custom OID ditambahkan (opsional, dengan filter vendor kalau perlu)
- [ ] Scan dijalankan, semua host penting berstatus `ok`
- [ ] Asset network muncul di /assets dan detailnya terisi (serial, vendor, model, OID)
- [ ] Untuk switch: *Kumpulkan port map* aktif, kolom **Port map** terisi, dan
      **Agents → Port map** menampilkan MAC ↔ port (endpoint yang dikenal ikut tertaut)
- [ ] Cek badge `uplink?`: port trunk/uplink memang wajar punya banyak MAC
- [ ] Jadwalkan scan rutin: saat ini manual; untuk otomatis, tambahkan cron/worker nanti
      (belum ada scheduler scan di versi ini)

## Referensi

- Lansweeper Classic — *Scan extra SNMP data with custom OID scanning*:
  <https://docs.lansweeper.com/classic/docs/scan-extra-snmp-data-with-custom-oid-scanning>
- OID standar: `SNMPv2-MIB` (1.3.6.1.2.1.1), `IF-MIB` (1.3.6.1.2.1.2),
  `ENTITY-MIB` (1.3.6.1.2.1.47).