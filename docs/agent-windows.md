# Panduan menjalankan `raniPush.exe` (Windows)

Panduan langkah demi langkah memasang agent **raniPush** di laptop/PC Windows supaya
inventaris (hardware, software, user, security) terkirim ke server RANI dan muncul di
dashboard.

**Agent 0.2+ tidak butuh token atau langkah enroll.** Cukup jalankan
`raniPush.exe <ip:port>` — server mengenali PC dari `machine_id` (MachineGuid Windows)
dan otomatis mendaftarkannya pada push pertama.

- Server dev: `http://192.168.88.92:8091`
- Binary: unduh dari UI `http://192.168.88.92:8091/agents` (bagian **Download agent**)
  → `raniPush-signed.exe` (disarankan, ±7,3 MB)
- Log agent: `C:\ProgramData\Rani\raniPush.log`
- Config agent: `C:\ProgramData\Rani\config.json` (hanya berisi server + interval)
- Spool offline: `C:\ProgramData\Rani\spool\`

---

## 0. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| OS | Windows 10 / 11 (x64) |
| Hak akses | PowerShell **as Administrator** (untuk tulis `C:\ProgramData` + Task Scheduler) |
| Jaringan | Bisa reach `192.168.88.92:8091` (tes: `Test-NetConnection 192.168.88.92 -Port 8091`) |
| Token | **Tidak perlu** |

Tidak perlu install Python, .NET, atau agent lain — exe sudah self-contained.

---

## 1. Ambil file exe

**Cara utama — dari browser (login RANI dulu):**

1. Buka `http://192.168.88.92:8091/agents`
2. Panel **Download agent (Windows)** → klik **Download** pada `raniPush-signed.exe`
3. Simpan ke `C:\Rani\`

Tanpa login, unduhan ditolak (401) — memang begitu yang diinginkan.

**Alternatif dari mesin Linux (server):**

```bash
scp root@192.168.88.92:/root/RaniProject/ProjectDev/release/raniPush-signed.exe .
```

Cek file tidak korup (opsional tapi disarankan) — hash diumumkan setiap build:

```powershell
Get-FileHash .\raniPush-signed.exe -Algorithm SHA256
```

---

## 2. Push pertama (tanpa token)

PowerShell **as Administrator**, di folder tempat exe berada:

```powershell
cd C:\Rani
Unblock-File .\raniPush-signed.exe
.\raniPush-signed.exe 192.168.88.92:8091
```

Output sukses:

```
push ok: report=39a25539-... asset=None agent=7cc9ff57-... next=3600s
```

- `agent=<uuid>` = server mendaftarkan PC ini otomatis (mode `direct`, tanpa secret).
- `exit code 0` = terkirim **atau** terspool (akan dicoba lagi otomatis).
- `exit code 1` = gagal fatal (alamat server salah, payload ditolak skema, atau server
  dimatikan mode tanpa token — lihat `raniPush.log`).

Verifikasi di UI:

- `http://192.168.88.92:8091/assets` → hostname PC muncul (badge **online**)
- Klik hostname → tab **Hardware / Software / Users / Security / Network** terisi
- Menu **Agents** → agent baru dengan nama hostname PC, kolom *mode* = `direct`

Kalau PC ini sudah pernah dilaporkan, push berikutnya hanya mengirim **delta**
(software yang baru dipasang/dihapus), bukan snapshot ulang.

> Kalau ingin PC benar-benar tidak bisa push tanpa kredensial, set
> `RANI_TOKENLESS_PUSH=0` di `.env` server lalu semua agent wajib pakai token + HMAC
> (lihat lampiran di bawah).

---

## 3. Jadwalkan otomatis (Task Scheduler)

### Opsi A — skrip installer (paling cepat)

Unduh `install-cert.ps1` (bila perlu signature) dan `scripts\install-agent.ps1` dari
repo, letakkan bersama exe, lalu:

```powershell
.\install-agent.ps1 -Server 192.168.88.92:8091
```

Skrip melakukan: copy exe ke `C:\Rani`, daftarkan task `RaniPush` (SYSTEM, tiap 60
menit), lalu push pertama. **Tanpa** `-Token` — tidak ada enroll.

### Opsi B — manual dengan schtasks

```powershell
schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f `
  /tr "C:\Rani\raniPush-signed.exe 192.168.88.92:8091"
schtasks /run   /tn RaniPush
schtasks /query /tn RaniPush /v /fo LIST
```

Untuk interval lain (mis. 15 menit) gunakan Task Scheduler GUI → *Create Task* →
Triggers → *Repeat task every 15 minutes*.

Server bisa mengubah interval lewat field `next_interval_s` pada respons push; agent
menyimpannya dan memakai nilai itu pada run berikutnya (Task Scheduler tetap pemanggilnya,
jadi interval efektif = maksimum antara jadwal task dan nilai server).

---

## 4. Referensi CLI

| Perintah | Fungsi |
|---|---|
| `raniPush.exe <server>` | collect + push langsung (mode default, tanpa token) |
| `raniPush.exe` | collect + push memakai server terakhir yang tersimpan di config |
| `raniPush.exe --collect` | cetak payload JSON ke stdout, **tidak** mengirim |
| `raniPush.exe --from-file <path> <server>` | kirim payload dari file (uji/troubleshoot) |
| `raniPush.exe --enroll <token> <server>` | opsional/legacy: enroll → pakai HMAC |

`<server>` boleh `192.168.88.92` (port default 8091), `192.168.88.92:8091`, atau
`http://192.168.88.92:8091`.

Exit code: **0** = sukses/terspool, **1** = gagal fatal (alamat server tidak ada, 401/422
dari server, payload tidak bisa dibaca). Kegagalan jaringan/5xx/429 **tidak** membuat
exit 1: payload di-spool dan dicoba lagi pada run berikutnya — detailnya di
`raniPush.log`.

---

## 5. Data yang dikirim

| Grup | Isi |
|---|---|
| identity | MachineGuid, hostname, domain/domain-joined |
| hardware | serial, vendor, model, chassis, BIOS, CPU, RAM, disk, GPU, monitor |
| os | caption, version, build, install date, locale, timezone, uptime, arsitektur |
| network | per interface: nama, MAC, IPv4/IPv6, subnet, gateway, DNS, DHCP |
| software | daftar Uninstall registry HKLM + HKCU (nama, versi, vendor, tanggal install) |
| users | user aktif, user logged-on, anggota grup Administrators |
| security | antivirus + status update, profil firewall, BitLocker, TPM, Secure Boot, pending reboot |

Tidak ada file dokumen, isi disk, password, atau key yang dikirim. Payload hanya metadata
inventaris dan divalidasi terhadap `schema/agent_payload_v1.json` di server.

---

## 6. Troubleshooting

Semua kejadian dicatat di `C:\ProgramData\Rani\raniPush.log`:

```powershell
Get-Content C:\ProgramData\Rani\raniPush.log -Tail 30
```

| Gejala | Cek / solusi |
|---|---|
| `push gagal (401)` | agent di-revoke, atau server memakai `RANI_TOKENLESS_PUSH=0` (maka perlu token + HMAC), atau `X-Rani-Agent-Id` dikirim tanpa signature |
| `push gagal (401): {"detail":"agent tidak dikenal/direvoke"}` saat push ke server **berbeda** | config masih menyimpan `agent_id`/`agent_secret` hasil enroll server lama — argumen alamat hanya mengganti server, bukan identitas. Agent versi baru otomatis membuang identitas itu saat target berubah; paksa manual: `.\raniPush.cmd --reset-identity`, atau pisahkan config per server dengan `set RANI_CONFIG_DIR=C:\Rani\cfg-nama` |
| `push gagal (400)` | header wajib hilang / `agent-id tanpa signature` — biasanya config lama hasil enroll; hapus `C:\ProgramData\Rani\config.json` lalu jalankan ulang |
| `push gagal (409)` | nonce replay (jam PC mundur) → sinkronkan waktu Windows: `w32tm /resync` |
| `push gagal (422)` | payload tidak lolos skema → kirim output `--collect` untuk diagnosa |
| `push gagal (429)` | terlalu sering push (>30/menit/agent) → naikkan interval task |
| `Connection refused` / `timed out` | server mati atau port diblokir: `Test-NetConnection 192.168.88.92 -Port 8091` |
| exit 1 tanpa pesan | jalankan manual di PowerShell (bukan lewat task) untuk melihat log |
| Hardware/software kosong | jalankan `--collect` lalu cek apakah PowerShell/WMI membatasi; jalankan sebagai admin/SYSTEM |
| `running scripts is disabled` | untuk skrip .ps1: `powershell -ExecutionPolicy Bypass -File .\install-agent.ps1 ...` |
| Task jalan tapi data tidak update | `schtasks /query /tn RaniPush /v /fo LIST` → lihat *Last Run Result* (0x0 = sukses) |

Reset konfigurasi lokal (pindah server / config rusak):

```powershell
Remove-Item C:\ProgramData\Rani\config.json
.\raniPush-signed.exe 192.168.88.92:8091
```

Atau lebih halus (hanya membuang identitas enroll, menyisakan server + interval):

```powershell
.\raniPush.cmd --reset-identity
```

Satu PC boleh push ke beberapa server: pakai config terpisah per server
(`set RANI_CONFIG_DIR=C:\Rani\cfg-<nama>` sebelum menjalankan agent), karena
`agent_secret` hasil enroll hanya sah di server yang menerbitkannya.

Cabut akses PC (hilang/dicuri): UI **Agents** → tombol **Revoke**. Push berikutnya dari PC
tersebut ditolak 401 (machine_id tetap dikenali, jadi tidak otomatis mendaftar ulang).

---

## 7. Uninstall

```powershell
schtasks /delete /tn RaniPush /f
Remove-Item -Recurse -Force C:\Rani
Remove-Item -Recurse -Force C:\ProgramData\Rani
```

Setelah itu revoke agent-nya di UI supaya tidak tersisa sebagai agent aktif.

---

## 8. Kalau Windows memblokir `raniPush.exe` (SmartScreen / Smart App Control)

Windows memblokir exe yang belum punya reputasi signature. Tiga jenis blokir yang
berbeda dan penanganannya tidak sama:

| Yang muncul | Penyebab | Bisa "Run anyway"? |
|---|---|---|
| "Windows protected your PC" (More info → Run anyway) | **SmartScreen** untuk file hasil download (Mark-of-the-Web) | Ya |
| "This app can't run because it can't be verified" / exe hilang tanpa pesan | **Smart App Control** (Windows 11, mode enforce) | **Tidak** — harus sign atau pakai paket portable |
| "Your organization's policy blocks this app" | **ASR rule** Defender / kebijakan domain | Tidak — perlu izin IT |

Diagnosa di PC target (PowerShell):

```powershell
# 0/2 = Smart App Control off atau evaluation; 1 = enforce (blokir aplikasi tak dikenal)
Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy `
  -Name VerifiedAndReputablePolicyState -ErrorAction SilentlyContinue

# apakah file masih membawa tanda "hasil download"?
Get-Item .\raniPush-signed.exe -Stream Zone.Identifier -ErrorAction SilentlyContinue

# aturan ASR yang aktif (mis. "block executable unless prevalence/age/trusted")
Get-MpPreference | Select-Object -ExpandProperty AttackSurfaceReductionRules_Ids
```

### Solusi A — buka blokir file (cukup untuk SmartScreen)

```powershell
Unblock-File .\raniPush.exe
```

Lalu jalankan. Kalau dialog masih muncul: **More info → Run anyway**. Ini hanya
menghapus Mark-of-the-Web; tidak mengubah proteksi sistem.

### Solusi B — pakai exe bertanda tangan + pasang sertifikat internal

`raniPush-signed.exe` (ditandatangani sertifikat code-signing internal RANI + timestamp)
dan `rani-push-signing.cer` sudah tersedia di halaman **Download agent**. Sertifikat dan
`install-cert.ps1` juga bisa diunduh dari halaman yang sama, jadi tidak perlu scp.

Di PC target (Administrator):

```powershell
.\install-cert.ps1 -CerPath .\rani-push-signing.cer
Get-AuthenticodeSignature .\raniPush-signed.exe | Format-List Status, SignerCertificate
# Status harus "Valid"
```

Sertifikat yang dipakai sekarang:

- Subject: `CN = RANI Internal Code Signing, O = RANI Internal, C = ID`
- SHA-256: `54:1E:A4:CB:AE:17:09:0B:AC:E6:73:35:1D:4A:DF:82:72:3C:E8:74:0F:F7:C3:4E:D7:25:6C:88:80:88:F7:63`
- Berlaku: 14 Nov 2026 → 13 Nov 2029

Batasnya: sertifikat **self-signed** menghilangkan status "unsigned"/"unknown publisher",
tapi **tidak** memberi reputasi SmartScreen dan **tidak** menembus Smart App Control
mode enforce. Untuk PC di luar kendali kita (atau SAC aktif), perlu sertifikat
code-signing dari CA publik (OV/EV) — itu berbiaya, jadi untuk internal cukup
sertifikat ini + GPO/Intune untuk distribusi.

Buat ulang signature kapan pun setelah build:

```bash
bash scripts/build-exe.sh      # exe tanpa signature
bash scripts/sign-exe.sh       # → release/raniPush-signed.exe + sertifikat publik
```

### Solusi C — paket portable tanpa exe buatan sendiri (paling tahan blokir)

`raniPush-portable.zip` (tombol download di halaman **Agents**) berisi Python 3.13
embeddable resmi (python.exe ditandatangani Python Software Foundation) + `raniPush.py`
+ `raniPush.cmd`. Tidak ada binary buatan kita, jadi tidak ada yang bisa ditolak sebagai
"untrusted exe".

```powershell
# extract dulu, mis. ke C:\Rani-portable
cd C:\Rani-portable
Unblock-File .\python\python.exe, .\raniPush.py, .\raniPush.cmd
.\raniPush.cmd 192.168.88.92:8091

# jadwalkan
schtasks /create /tn RaniPush /sc hourly /ru SYSTEM /rl HIGHEST /f `
  /tr "C:\Rani-portable\raniPush.cmd 192.168.88.92:8091"
```

Perilaku, config, log (`C:\ProgramData\Rani\raniPush.log`), spool, dan endpoint sama
persis dengan versi exe. Rebuild paket: `bash scripts/build-portable.sh`.

### Mana yang dipakai?

| Kondisi PC | Pilihan |
|---|---|
| Laptop pribadi, cuma muncul "Windows protected your PC" | Solusi A |
| PC kantor/domain, IT bisa distribusi sertifikat | Solusi B (sign + `install-cert.ps1`) |
| Smart App Control mode enforce / AV memblokir exe apa pun | Solusi C (portable) |
| Perlu dipasang massal tanpa interaksi user | Solusi B + GPO/Intune, atau Solusi C |

Jangan mematikan Defender/ASR atau menambah folder exclusion sebagai solusi rutin —
kalau memang perlu, minta persetujuan pemilik infra dan catat alasannya.

### Solusi D — pesan `blocked by your organization` (WDAC / AppLocker / ASR)

Pesan ini **bukan** SmartScreen: yang menolak adalah kebijakan mesin/domain, jadi
tidak ada langkah di sisi server yang bisa membuka blokir. Urutannya:

1. **Pastikan penyebabnya** di PC target (PowerShell admin) — jangan menebak:

   ```powershell
   # 0/2 = Smart App Control off/evaluation, 1 = enforce
   Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -Name VerifiedAndReputablePolicyState
   # ASR rule Defender yang aktif (GUID)
   (Get-MpPreference).AttackSurfaceReductionRules_Ids
   # bukti penolakan: ID 3077 = blokir WDAC, 8004/8003 = AppLocker
   Get-WinEvent -LogName 'Microsoft-Windows-CodeIntegrity/Operational' -MaxEvents 15 |
     Format-Table TimeCreated,Id,Message -Wrap
   ```

2. **Coba Jalur A (portable) lebih dulu** — kalau `python.exe` diizinkan kebijakan,
   tidak perlu ubah GPO sama sekali. Ini jalur tercepat untuk trial.

3. **Kalau tetap diblokir**, minta IT menambah **satu** aturan allowlist. Bahan yang
   dibutuhkan sudah tersedia di halaman `/agents/push` (kartu
   “Windows memblokir raniPush”): SHA256 tiap artefak + subject sertifikat.
   Template permintaan:

   ```text
   Subjek: Allowlist aplikasi internal RANI (raniPush) untuk inventaris aset IT

   Aplikasi : raniPush (agent inventaris RANI, internal)
   Tujuan   : push inventaris hardware+software tiap 60 menit ke server LAN
             http://192.168.88.92:8091 (HTTP, tanpa internet)

   Opsi allowlist (pilih satu):
   a) Hash rule (paling ketat, per versi file):
        raniPush-signed.exe    SHA256 <lihat /agents/push>
        raniPush.exe           SHA256 <lihat /agents/push>
        raniPush-portable.zip  SHA256 <lihat /agents/push>
   b) Publisher rule (bertahan saat versi naik):
        CN=RANI Internal Code Signing, O=RANI Internal, C=ID
        Sertifikat: /downloads/rani-push-signing.cer
        (import ke Trusted Root + TrustedPublisher lewat scripts/install-cert.ps1)
   c) Bila kebijakan tidak bisa diubah: izinkan python.exe (PSF-signed) agar
      paket portable bisa jalan.

   Bukti penolakan saat ini: <tempel output CodeIntegrity/Operational + GUID ASR>
   ```

Catatan: jangan menonaktifkan Smart App Control sebagai solusi (di Windows 11 itu
permanen sampai instalasi ulang), dan jangan pakai folder exclusion permanen.

---

## 9. Cek cepat (cheat sheet)

```powershell
# 1. server hidup?
Test-NetConnection 192.168.88.92 -Port 8091

# 2. unduh raniPush-signed.exe dari http://192.168.88.92:8091/agents, lalu:
cd C:\Rani
Unblock-File .\raniPush-signed.exe
.\raniPush-signed.exe 192.168.88.92:8091
Get-Content C:\ProgramData\Rani\raniPush.log -Tail 5

# 3. otomatiskan
.\install-agent.ps1 -Server 192.168.88.92:8091
```

Selesai — aset muncul di `http://192.168.88.92:8091/assets` dan ikut ter-update tiap
interval tanpa perlu scan jaringan atau kredensial domain.

---

## Lampiran — mode token + HMAC (legacy, opsional)

Dipakai hanya bila server di-set `RANI_TOKENLESS_PUSH=0`, atau bila memang ingin setiap
push ditandatangani HMAC-SHA256 dengan secret per-PC.

1. UI **Agents** → panel *Enrollment token* → **Buat** (sekali pakai, default 24 jam).
2. Di PC:

```powershell
.\raniPush-signed.exe --enroll <TOKEN> 192.168.88.92:8091
.\raniPush-signed.exe 192.168.88.92:8091
```

Enroll menyimpan `agent_id` + signing key di `C:\ProgramData\Rani\config.json`; file itu
jadi kredensial (jangan dicopy ke PC lain). Setelah enroll, agent otomatis mengirim
`X-Rani-Agent-Id` + `X-Rani-Signature`; menghapus config mengembalikan agent ke mode
langsung tanpa token.

| Pesan enroll | Artinya |
|---|---|
| `token tidak dikenal` (401) | token salah ketik / bukan dari server ini |
| `token sudah dipakai` (409) | token dipakai PC lain → buat token baru |
| `token kedaluwarsa` (410) | lewat TTL → buat token baru |
| `Connection refused` / timeout | server tidak reachable → cek IP/port/firewall |