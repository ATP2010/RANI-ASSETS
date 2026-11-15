# Actions — aksi cepat di menu Assets (gaya Lansweeper)

Menu Assets / detail asset punya **Actions**: tombol aksi cepat terhadap sebuah
asset (buka web, remote desktop, share file, SSH, VNC, **skrip dijalankan di PC
pengguna**), meniru *Lansweeper Classic → Asset Pages → Actions*
(<https://docs.lansweeper.com/classic/docs/create-and-run-actions>).

Tiga jenis action:

| Jenis | Contoh | Dieksekusi di |
|---|---|---|
| `link` | `rdp://{ipaddress}`, `https://{fqdn}` | browser → handler protokol OS |
| `copy` | `mstsc /v:{ipaddress}` | clipboard klien |
| `script` | `ping.bat {ipaddress}` | **PC orang yang klik** — seperti Lansweeper **Shell Execute**: extension Chromium + native host (`rani-action-host.exe`) |

Action script bekerja seperti Lansweeper: tombol di web memanggil **ekstensi
browser "RANI Actions"** (Edge/Chrome), ekstensi mengirim pesan lewat **native
messaging** ke **`rani-action-host.exe`** di PC pengguna, host men-download skrip
dari server (token HMAC, 5 menit), lalu **mengeksekusinya di PC itu** dengan
argumen asset. Kredensial user dipakai apa adanya — tidak pernah dikirim ke server.

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

## 7. Action script — skrip dijalankan di PC pengguna (RANI Actions extension)

Ini pola Lansweeper persis: alih-alih mendaftarkan protokol OS (`raniaction://`),
RANI menyediakan **ekstensi Chromium "RANI Actions"** (Edge/Chrome). Pengguna
memasang **satu paket** (ekstensi + native host, dari dua file unduhan) dan bisa
langsung klik action di web RANI — tanpa protokol OS, tanpa langkah manual per aksi.

```
PC pengguna                                                 Server RANI
┌─────────────────────────────┐  klik "Ping (skrip)"        │
│ Browser (Edge/Chrome)        │ ──────────────────────────┐ │
│   ↓ content.js (capture)     │                            │ │
│ RANI Actions extension       │   GET /actions/files/…     │ │
│   ↓ chrome.runtime.          │ ◀──────────────────────────┤ │
│ nativeMessaging              │                            │ │
│   ↓                          │   200 OK ping.bat          │ │
│ rani-action-host.exe         │ ◀──────────────────────────┘ │
│   ↓ validasi (origin, ext,   │                              │
│     arg whitelist)           │                              │
│ cmd /c ping.bat 192.168.1.5  │                              │
└─────────────────────────────┘
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
4. **Perintah**: `rdp.bat {ipaddress}` — nama file + args (disubstitusi dari asset
   saat klik).
5. Centang *Tanyakan konfirmasi* untuk RDP/restart; *Advanced* untuk aksi
   berisiko. Simpan.

File harus ada di folder `./actions/` server — penyimpanan ditolak bila belum ada.

### 7.3 Menginstall extension + native host (sekali per PC, tanpa admin)

Unduh dua file dari menu **Agents** di web (butuh login, bagian "RANI Actions") atau
`http://<server>:8091/downloads/…`:

1. `rani-action-host.exe` (native host, ~7 MB)
2. `rani-actions-extension.zip` (ekstensi + installer)

Lalu:

```powershell
# dari folder hasil unzip:
powershell -ExecutionPolicy Bypass -File .\install-extension.ps1 -ServerUrl https://rani.corp.local:8091
```

Installer (`install-extension.ps1`) melakukan **semua** konfigurasi tanpa admin:

1. Menyalin `rani-action-host.exe` ke `%ProgramData%\rani-action\rani-action-host.exe`;
2. Menulis `config.json` berisi **origin server RANI** Anda;
3. Menulis native messaging manifest `com.rani.action_host.json`
   (`allowed_origins = chrome-extension://lfkhhkhfcfkcmeefpijfoojicckpnkjo/`);
4. Mendaftarkan di
   `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.rani.action_host`,
   `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.rani.action_host`, dan
   `HKCU\Software\Chromium\NativeMessagingHosts\com.rani.action_host`.

Dan pasang ekstensi:

1. Buka `edge://extensions` (Chrome: `chrome://extensions`);
2. Aktifkan **Developer mode** (toggle kanan atas);
3. Klik **Load unpacked** → pilih folder hasil unzip;
4. Klik ikon puzzle → **RANI Actions** → **Enable on this site** (bila diminta).

ID ekstensi selalu `lfkhhkhfcfkcmeefpijfoojicckpnkjo` (dikunci oleh field `"key"` di
manifest), sehingga native manifest selalu valid tanpa diatur manual. Untuk banyak PC,
mass-deploy via GPO/SCCM/Intune (tiga file, tanpa admin).

**Uninstall**: dari folder unzip jalankan `uninstall-extension.ps1` (atau
`install-extension.ps1 -ServerUrl … -Uninstall`), lalu hapus ekstensi dari halaman
extensions.

### 7.4 Alur klik, langkah demi langkah

1. User membuka RANI di Edge/Chrome, hover hostname di Assets, klik `Ping (skrip)`.
2. `content.js` (capture) melihat tombol `[data-rani-action]` → `preventDefault` →
   kirim pesan ke service worker ekstensi.
3. Service worker memanggil `chrome.runtime.sendNativeMessage('com.rani.action_host', …)`.
4. Native host memvalidasi: `file` polos + ekstensi diizinkan, argumen hanya
   `[A-Za-z0-9._:-]`, `exp` belum kedaluwarsa, `origin` == `server_origin` di `config.json`.
5. Native host mengunduh `https://<server>/actions/files/ping.bat?exp=…&sig=…`
   (divalidasi ulang di server: filename, ekstensi, HMAC 5 menit) ke
   `%TEMP%\rani-action\run-<acak>\`.
6. Native host menjalankan `cmd /c "ping.bat" 192.168.88.10` — jendela ping/terminal
   terbuka di PC user. Kredensial RDP tetap diminta Windows saat aksi RDP.

### 7.5 Keamanan

- Ekstensi hanya aktif di halaman RANI (marker `<meta name="rani" content="app">`);
  di situs lain ekstensi diam total.
- Native host hanya menerima `origin` yang cocok dengan `server_origin` di
  `config.json` (dibuat installer).
- Tidak ada akses ke file/passwords di browser; native host hanya menjalankan file
  yang ada di `./actions/` server — divalidasi di **tiga lapis** (form Setup,
  endpoint download, native host).
- Argumen divalidasi whitelist karakter `[A-Za-z0-9._:-]` — tidak bisa menyisipkan
  `;` / `&` / `|` / spasi perintah shell.
- Token HMAC (`sig`) berlaku 5 menit (`RANI_ACTIONS_URLTTL_S`); `exp` kedaluwarsa
  ditolak di server maupun di native host. Token dibuat per render; tidak di-cache.
- Folder `./actions/` di-*mount read-only* ke container; file di dalamnya ada di git.
- Action script bukan alat deployment: skrip destruktif **wajib** diaktifkan
  *Tanyakan konfirmasi* + tercatat di `audit_logs`.
- Tidak ada kredensial yang disimpan; setiap aksi dijalankan dengan hak user yang klik.

### 7.6 Troubleshooting

| Gejala | Sebab / solusi |
|---|---|
| Klik action tidak melakukan apa-apa | Ekstensi belum terpasang / belum diizinkan di situs ini; atau native host belum dipasang. Klik ikon RANI di toolbar — hijau "native host terhubung" atau merah dengan pesan penyebab. |
| Popup ekstensi: "native host tidak terjangkau" | Pasang native host (§7.3). Cek `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.rani.action_host` menunjuk ke `com.rani.action_host.json` yang benar. |
| "origin tidak diizinkan" | `config.json` berisi server lain — pasang ulang (`install-extension.ps1 -ServerUrl …`). |
| "token kedaluwarsa" | Halaman terbuka >5 menit — reload, klik lagi. |
| "ekstensi … tidak diizinkan" | Ekstensi coba mengunduh file dengan ekstensi di luar whitelist — perbaiki action di Setup → Actions. |
| Klik tidak terjadi (tombol inert) | Ekstensi belum aktif di situs ini: klik ikon puzzle → **RANI Actions** → **Enable on this site**. |
| Action script tidak muncul di menu | Action *Enabled* belum dicentang di Setup → Actions, atau action ini *Advanced* (masuk grup Advanced). |
| mstsc / window tidak tampak | Mungkin terbuka di desktop lain / minimized; coba `Alt+Tab`. |

Skrip contoh tersimpan di repo: `actions/rdp.bat`, `actions/ping.bat`,
`actions/compmgmt.bat`, `actions/services.bat`, `actions/perfmon.bat`.
Source ekstensi + native host: `extension/`, `agent/rani_action_host.py`.
Fallback lama (protokol OS `raniaction://` + handler PowerShell) masih tersedia di
`actions/handler/` — dipakai bila ekstensi tidak bisa dipasang di browser tertentu.
