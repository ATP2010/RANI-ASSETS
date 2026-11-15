# Actions — aksi cepat di menu Assets (gaya Lansweeper)

Menu Assets dan halaman detail asset punya **Actions**: tombol aksi cepat untuk
tindakan umum terhadap sebuah asset (buka web, remote desktop, share file, SSH, VNC),
meniru *Lansweeper Classic → Asset Pages → Actions*
(<https://docs.lansweeper.com/classic/docs/create-and-run-actions>).

Actions adalah **hyperlink yang dieksekusi di mesin klien** — bukan di server. Tidak
ada credential, tidak ada agent di-deploy, dan server tidak membuka koneksi ke PC
target; klien (browser Anda) yang men-trigger handler protokol atau halaman web.

## 1. Di mana Actions tampil

| Tempat | Bentuk |
|---|---|
| Menu **Setup → Actions** (`/setup/actions`) | halaman untuk **mengelola** daftar action (khusus `setup.manage`) |
| `/assets` — hover di hostname | popup overview (IP, MAC, OS, serial, port/switch) + daftar Actions |
| Halaman detail asset `/assets/{id}` | tombol **Actions** di kanan atas (di samping badge status) |

Popup overview juga menampilkan: IP, MAC, OS, domain, serial, dan **Port / Switch**
(port + IP switch via port map F2.4b) untuk PC, atau jumlah MAC/port untuk switch.

## 2. Daftar action

Parameter diisi otomatis dari field asset (pola Lansweeper: `{ipaddress}`,
`{assetname}`, `{fqdn}`, `{dnsname}`, `{domain}`, `{mac}`, `{tag}`):

| Action | URL / perintah | Keterangan |
|---|---|---|
| Buka di browser (HTTP) | `http://{ipaddress}` | probe web server / print server / panel |
| Buka di browser (HTTPS) | `https://{ipaddress}` | idem, TLS |
| Buka berbagi file (C$) | `file:///{ipaddress}/c$` | Windows share admin (Explorer) |
| Remote Desktop (RDP) | `rdp://{ipaddress}` | butuh handler protokol `rdp://` (lihat §4) |
| SSH | `ssh://{ipaddress}` | butuh handler `ssh://` (PuTTY/OpenSSH) |
| VNC | `vnc://{ipaddress}` | butuh handler `vnc://` (RealVNC/TigerVNC) |
| Salin `mstsc /v:{ipaddress}` | clipboard | tempel di Run → selalu berhasil (Windows) |
| Salin alamat IP / MAC / hostname | clipboard | men-tag tiket/catatan |

Action yang membutuhkan IP disembunyikan otomatis bila asset tidak punya `ip_last`.

## 3. Mengelola action — menu Setup → Actions

Buka **Setup → Actions** (perlu permission `setup.manage`; `setup.view` hanya
melihat). Dari sini Anda bisa:

- **Membuat action baru**: nama, jenis `link` (URL/protokol) atau `copy` (teks ke
  clipboard), perintah/URL dengan placeholder, urutan, dan tiga saklar: *Enabled*,
  *Advanced*, *Tanyakan konfirmasi*.
- **Ubah, duplikat, hapus**, **naik/turunkan urutan**, dan **enable/disable** cepat.
- **Advanced** memisahkan action ke grup "Advanced" di popup/dropdown (Lansweeper:
  advanced actions untuk tugas berisiko, basic untuk yang ringan).
- **Tanyakan konfirmasi** memicu dialog konfirmasi browser sebelum action berjalan
  (dipakai untuk RDP/SSH/VNC/share).
- Pratinjau substitution action dengan asset contoh langsung di halaman.

Validasi sisi server: skema link harus diizinkan (`http`, `https`, `ftp`, `file`,
`rdp`, `ssh`, `telnet`, `vnc`, `winbox`, `mqtt`, `ldap`, `ldaps`), placeholder harus
dikenal (`{ipaddress}`, `{assetname}`, `{hostname}`, `{dnsname}`, `{fqdn}`,
`{domain}`, `{mac}`, `{tag}`, `{assetid}`). `javascript:`/`data:` ditolak.

Action default (seed migration `0007_asset_actions`): HTTP, HTTPS, share C$, RDP,
SSH, VNC, `mstsc /v:…`, salin IP/MAC/hostname — bisa diubah atau dimatikan.

Contoh action internal kantor (Zabbix): nama `Buka di Zabbix`, URL
`https://zabbix.corp.local/host.php?host={ipaddress}`, centang **Advanced**.

Action disimpan di tabel `asset_actions`; tidak ada konfigurasi di `.env`, tidak ada
credential.

## 4. Handler protokol (rdp://, ssh://, vnc://, file://)

Browser tidak punya handler bawaan untuk protokol ini; OS yang mendaftarkannya:

- **Windows RDP**: daftar `.reg` atau pakai tombol *Salin `mstsc /v:<ip>`* (paling
  andal). Windows App / `mstsc` bisa mendaftar `rdp://`.
- **SSH**: install [PuTTY](https://www.putty.org/) atau OpenSSH client; PuTTY
  mendaftarkan `ssh://` saat instalasi (atau centang di pengaturan).
- **VNC**: RealVNC Viewer mendaftarkan `vnc://`.
- **Akses share `\\IP\C$`**: Windows Explorer membuka `file:///<ip>/c$` bila user
  domain punya hak admin di share tersebut.

Jika tidak ada handler terdaftar, klik hanya memunculkan dialog "buka aplikasi" atau
diam saja — action tetap tersedia di mesin yang punya handler.

## 5. Keamanan & izin

- Actions hanya tampil untuk pemegang `assets.view` (default: role `reader` ke atas) —
  tindakan sebenarnya berjalan di klien dengan credential *Anda*, bukan credential
  aplikasi.
- Tidak ada action yang mengubah data di sisi server atau di PC target tanpa
  konfirmasi dari aplikasi eksternal (RDP/SSH/dll. justru meminta autentikasi).
- `file:///` dan `rdp://` dibatasi oleh kebijakan browser/OS Anda sendiri
  (SmartScreen, group policy) — perilaku sama seperti "klik link dari dokumen".
- Tidak ada placeholder yang membocorkan data: semua berasal dari field asset yang
  memang sudah tampil di halaman asset.

## 6. Troubleshooting

| Gejala | Solusi |
|---|---|
| Klik action tidak melakukan apa-apa | Handler protokol belum terdaftar di OS; pakai *Salin `mstsc /v:…`* atau *Salin IP* |
| `file:///IP/c$` menolak akses | User Windows Anda tidak punya hak admin ke share; gunakan akun domain |
| Action hilang di daftar | Asset tidak punya `ip_last` — agent belum pernah push atau asset hasil scan tanpa host terdeteksi; atau action dimatikan di **Setup → Actions** (kolom Aktif) |
| Menu Setup tidak muncul | Role Anda tidak punya `setup.view`; minta admin beri permission `setup.view`/`setup.manage` di **Users → Role & akses** |
| Popup tidak muncul saat hover | Hanya perangkat dengan mouse; di touch/keyboard gunakan tab order + Enter pada hostname |
| Popup memotong tepi layar | Geser horizontal; popup otomatis menyesuaikan (max-width 340px) |
