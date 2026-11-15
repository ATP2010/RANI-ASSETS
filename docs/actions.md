# Actions — aksi cepat di menu Assets (gaya Lansweeper)

Menu Assets / detail asset punya **Actions**: tombol aksi cepat terhadap sebuah
asset (buka web, remote desktop, share file, SSH, VNC, **skrip dijalankan di PC
pengguna**), meniru *Lansweeper Classic → Asset Pages → Actions*
(<https://docs.lansweeper.com/classic/docs/create-and-run-actions>).

Tiga jenis action:

| Jenis | Contoh | Dieksekusi di |
|---|---|---|
| `link` | `rdp://{ipaddress}`, `https://{fqdn}` | browser → handler OS (`rdp://`, `ssh://`, …) |
| `copy` | `mstsc /v:{ipaddress}` | clipboard klien |
| `script` | `ping.bat {ipaddress}` | **PC orang yang klik** — download dari server lalu dijalankan di sana (pola `lansweeper$`) |

Semua dieksekusi **di mesin klien**, bukan di server dan bukan di PC target;
browser pengguna yang menjalankan aksi dengan kredensial *pengguna itu sendiri*.

## 1. Di mana Actions tampil

| Tempat | Bentuk |
|---|---|
| Menu **Setup → Actions** (`/setup/actions`) | halaman untuk **mengelola** daftar action (lihat §3) |
| `/assets` — hover di hostname | popup overview (IP, MAC, OS, serial, port/switch) + daftar Actions |
| Halaman detail asset `/assets/{id}` | tombol **Actions** di kanan atas (di samping badge status) |

## 2. Daftar action bawaan

Ter-seed dari migration `0007_asset_actions` (+`0008` untuk contoh script):

| Action | Jenis | URL / perintah |
|---|---|---|
| Buka di browser (HTTP/HTTPS) | link | `http://{ipaddress}` / `https://{ipaddress}` |
| Buka berbagi file (C$) | link | `file:///{ipaddress}/c$` |
| Remote Desktop (RDP) | link | `rdp://{ipaddress}` (konfirmasi ✓) |
| SSH | link | `ssh://{ipaddress}` (konfirmasi ✓) |
| VNC | link | `vnc://{ipaddress}` (konfirmasi ✓) |
| Salin `mstsc` untuk RDP | copy | `mstsc /v:{ipaddress}` |
| Salin alamat IP / MAC / hostname | copy | `{ipaddress}` / `{mac}` / `{hostname}` |
| Ping (skrip) | script | `ping.bat {ipaddress}` |

Placeholder: `{ipaddress}` `{assetname}` `{hostname}` `{dnsname}` `{fqdn}` `{domain}` `{mac}` `{tag}` `{assetid}`; `{actionpath}` = URL folder skrip (`<server>/actions/files/`).

## 3. Mengelola action — menu Setup → Actions

Buka **Setup → Actions** (perlu `setup.manage`; `setup.view` hanya melihat):

- **Membuat**: nama, jenis, perintah/URL/nama file skrip + args, urutan, saklar
  *Enabled*/*Advanced*/*Tanyakan konfirmasi*.
- **Ubah, duplikat, hapus, naik/turunkan urutan, enable/disable cepat.**
- *Advanced* memisahkan action ke grup "Advanced" (untuk tugas berisiko).
- *Tanyakan konfirmasi* memicu dialog konfirmasi browser dulu (dipakai RDP/SSH/VNC/share).
- Pratinjau substitution live di halaman (asset contoh).
- Validasi server: skema link dibatasi (`http, https, ftp, file, rdp, ssh, telnet,
  vnc, winbox, mqtt, ldap, ldaps`), placeholder harus dikenal, file script **harus ada
  di folder `./actions/` server** (dengan ekstensi diizinkan). `javascript:` /
  `data:` ditolak.
- Semua perubahan masuk `audit_logs` (`setup.action.*`).

Contoh action internal kantor (Zabbix): nama `Buka di Zabbix`, URL
`https://zabbix.corp.local/host.php?host={ipaddress}`, centang **Advanced**.

Untuk action script lihat §7.

## 4. Handler protokol (rdp://, ssh://, vnc://, file://)

Browser tidak punya handler bawaan protokol ini; OS yang mendaftarkannya:

- **Windows RDP**: tombol *Salin `mstsc /v:<ip>`* adalah jalan paling andal (tempel di
  Run). Windows App / `mstsc` dapat mendaftar `rdp://`.
- **SSH**: PuTTY atau OpenSSH client (PuTTY mendaftarkan `ssh://` saat instalasi).
- **VNC**: RealVNC Viewer mendaftarkan `vnc://`.
- **Share `\\IP\C$`**: Windows Explorer membuka `file:///<ip>/c$` bila user Anda punya
  hak admin di share.

Jika tidak ada handler terdaftar, klik tidak melakukan apa-apa. Action tetap tersedia
bila mesin klien punya handler.

## 5. Keamanan & izin

- Actions tampil untuk pemegang `assets.view` (default `reader` ke atas). Aksi
  berjalan di klien dengan kredensial pengguna, bukan kredensial aplikasi.
- Tidak ada action yang mengubah data server atau PC target tanpa konfirmasi
  eksternal (RDP/SSH/dll. selalu meminta autentikasi sendiri).
- `file:///`, `rdp://` dibatasi kebijakan browser/OS klien (SmartScreen, GPO) —
  berlaku seperti klik link dari dokumen.
- Action script: klien hanya menerima file dari server RANI terdaftar (origin di
  `config.json` saat instalasi), ekstensi dibatasi, argumen hanya karakter aman,
  token HMAC berlaku 5 menit (lihat §7).
- Tidak ada placeholder yang membocorkan data — semua dari field asset yang memang
  sudah tampil di halaman asset.

## 6. Troubleshooting

| Gejala | Solusi |
|---|---|
| Klik action tidak melakukan apa-apa | Handler protokol belum terdaftar di OS; pakai *Salin `mstsc /v:…`* / *Salin IP* |
| `file:///IP/c$` menolak akses | User Windows Anda tidak punya hak admin ke share; gunakan akun domain |
| Action hilang di daftar | Asset tanpa `ip_last`; atau action dimatikan di **Setup → Actions** |
| Menu Setup tidak muncul | Role Anda tidak punya `setup.view`; minta admin atur permission di **Users → Role & akses** |
| Popup memotong tepi layar | Popup otomatis di atas/di bawah hostname; pada layar <720px isinya di-scroll |

## 7. Action script — skrip dijalankan di PC pengguna (`raniaction://`)

Seperti Lansweeper (`lansweeper$` + handler `lansweeper://`), RANI meniru alurnya:
skrip kecil disimpan di **server** (`./actions/`, read-only ke container); saat user
membuka web dan mengklik action, browser memanggil protokol `raniaction://` yang
terdaftar **di PC pengguna**; handler memvalidasi, mengunduh skrip dari server, dan
menjalankannya di PC itu dengan argumen asset (mis. IP).

```
PC pengguna                                                Server RANI
┌──────────────────────────┐   raniaction://run?f=ping.bat&exp=…&sig=…&a=192.168.1.5
│ Browser → HKCU protocol  │ ──────────────────────────────────────────────┐
│   ↓                      │                                                │
│ rani-action.ps1          │   GET /actions/files/ping.bat?exp=…&sig=…     │
│   ↓ validasi (origin,    │ ──────────────────────────────────────────────┤
│     ekstensi, args,      │                                                │
│     token HMAC 5 menit)  │   200 OK (bat, 129 B)                          │
│   ↓                      │ ◀───────────────────────────────────────────────┘
│ cmd /c ping.bat 192.168.1.5                                  ✓ user melihat hasil di PC sendiri
└──────────────────────────┘
```

### 7.1 Menulis skrip sendiri

Taruh di folder `./actions/` (ter-commit ke repo, di-mount read-only ke container):

```bat
:: actions/rdp.bat — Remote Desktop ke asset
@echo off
mstsc.exe /v:%1
```

```bat
:: actions/compmgmt.bat — Computer Management remote
@echo off
compmgmt.msc /computer=%1
```

Aturan: nama file polos `[A-Za-z0-9._-]`, ekstensi diizinkan `.bat .cmd .ps1 .exe .msi`,
tanpa subfolder. Skrip berjalan **di PC pengguna** dengan hak user yang klik. Taruh
informasi/argumen via placeholder action — jangan hardcode IP.

### 7.2 Mendaftarkan action di Setup → Actions

1. Buka **Setup → Actions** → *Action baru*.
2. **Nama**: mis. `Remote Desktop (RDP)`.
3. **Jenis**: `script (file server, klik → PC pengguna)`.
4. **Perintah**: `rdp.bat {ipaddress}` — nama file + args (args disubstitusi dari
   asset saat klik).
5. Centang *Tanyakan konfirmasi* untuk RDP/restart; centang *Advanced* untuk aksi
   berisiko. Simpan.

File harus ada di folder `./actions/` server — kalau tidak, penyimpanan ditolak dengan
pesan jelas. Pratinjau di halaman menampilkan `raniaction://run?f=rdp.bat&…&a=192.168.88.10`.

### 7.3 Menginstall handler di PC pengguna (tanpa admin)

Di setiap PC yang diizinkan menjalankan action script, jalankan **sekali**:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-action-handler.ps1 -ServerUrl https://rani.corp.local:8091
```

atau double-klik `actions/handler/install.bat https://rani.corp.local:8091`.

Installer (`install-action-handler.ps1`) bekerja dengan hak user biasa (HKCU):

1. Menyalin `rani-action.ps1` ke `%ProgramData%\RaniAction\rani-action.ps1`;
2. Menulis `config.json` berisi **origin server RANI** Anda
   (`{ "server_url": "https://rani.corp.local:8091" }`);
3. Mendaftarkan protokol `raniaction://` di
   `HKCU\Software\Classes\raniaction` →
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "…rani-action.ps1" "%1"`.

Tidak ada yang di-download / di-register di luar itu. Untuk banyak PC, mass-deploy via
GPO/SCCM/Intune (file-file kecil, tidak butuh admin).

**Uninstall**: di PC (sekali): `…uninstall-action-handler.ps1` atau hapus key
`HKCU\Software\Classes\raniaction` + folder `%ProgramData%\RaniAction`.

### 7.4 Alur klik, langkah demi langkah

1. User membuka RANI di browser, hover hostname di menu Assets, klik `Remote Desktop (RDP)`.
2. Browser melihat link `raniaction://run?f=rdp.bat&exp=…&sig=…&a=192.168.88.10` →
   Windows lookup `HKCU\Software\Classes\raniaction` → menjalankan PowerShell handler
   dengan URI itu.
3. Handler memvalidasi:
   - `f` = `rdp.bat` (tanpa path, ekstensi diizinkan);
   - `exp` belum kedaluwarsa (5 menit sejak halaman di-render);
   - `sig` HMAC valid terhadap filename + expiry (dihitung server dengan pepper);
   - `a` hanya karakter `[A-Za-z0-9._:-]` (anti command injection).
4. Handler mengunduh `https://<server-anda>/actions/files/rdp.bat` (divalidasi ulang
   di server: filename, ekstensi, HMAC) ke `%TEMP%\RANI`.
5. Handler menjalankan `cmd /c "…\rdp.bat" 192.168.88.10` — jendela mstsc terbuka
   di PC user, berisi IP target. Kredensial RDP tetap diminta oleh Windows.

### 7.5 Keamanan

- **Handler hanya mau men-download dari server RANI Anda** (origin di `config.json`).
  URI `raniaction://` menuju host lain diabaikan/dierror.
- Ekstensi dibatasi di **tiga** tempat: form Setup (validasi), endpoint download
  (`/actions/files/{file}`), dan handler klien (`.bat .cmd .ps1 .exe .msi`).
- Argumen divalidasi karakter-per-karakter (`[A-Za-z0-9._:-]`) — tidak bisa menyisipkan
  `;`/`&`/spasi perintah berbahaya. Placeholder `{ipaddress}`/`{fqdn}`/`{mac}` menghasilkan
  token yang selalu cocok.
- Token HMAC (`sig`) berlaku 5 menit; `exp` kedaluwarsa ditolak baik di server
  (`/actions/files/*`) maupun di handler. Token dibuat per render; tidak di-cache.
- Folder `./actions/` di-*mount read-only* ke container (`:ro`); file di dalamnya ada
  di repo git — tidak bisa ditulis dari dalam container.
- Action script bukan alat deployment: jika skrip bersifat destruktif (restart server,
  shutdown), Anda **wajib** mengaktifkan *Tanyakan konfirmasi*; log semua perubahan
  masuk `audit_logs`.
- Tidak ada kredensial yang disimpan, tidak ada langkah yang menulis ke PC tanpa aksi
  klik user.

### 7.6 Troubleshooting

| Gejala | Sebab / solusi |
|---|---|
| Klik action tidak melakukan apa-apa | Handler belum terpasang di PC ini / protokol tidak terdaftar; jalankan installer §7.3, cek `HKCU\Software\Classes\raniaction` |
| "konfigurasi tidak ditemukan" | `config.json` hilang; pasang ulang handler (`install-action-handler.ps1 -ServerUrl …`) |
| "token kedaluwarsa" | Halaman dibiarkan terbuka >5 menit — reload halaman, klik lagi |
| "server_url tidak valid" | `config.json` rusak; hapus `%ProgramData%\RaniAction\config.json`, pasang ulang |
| File terdownload tapi tidak jalan | Ekstensi tidak diizinkan (`.vbs` ditolak); antivirus/SmartScreen memblokir; coba jalankan file hasil download secara manual untuk melihat error |
| Action script tidak muncul di menu | Belum di-"Enabled" di Setup → Actions, atau nama file kosong/placeholder salah saat dibuat |
| `rdp.bat` membuka tapi mstsc error | `{ipaddress}` kosong (asset tidak punya `ip_last`); isi parameter lain atau perbaiki konektivitas |
| Popup/dropdown blank di browser | Refresh (Ctrl+Shift+R) — token action dibuat ulang saat halaman dimuat |

Skrip contoh tersimpan di repo: `actions/rdp.bat`, `actions/ping.bat`,
`actions/compmgmt.bat`, `actions/services.bat`, `actions/perfmon.bat`,
`actions/handler/{rani-action.ps1, install-action-handler.ps1, install.bat, uninstall-action-handler.ps1}`.
