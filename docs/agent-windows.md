# Panduan menjalankan `raniPush.exe` (Windows)

Panduan langkah demi langkah memasang agent **raniPush** di laptop/PC Windows supaya
inventaris (hardware, software, user, security) terkirim ke server RANI dan muncul di
dashboard.

- Server dev: `http://192.168.88.92:8091`
- Binary: `release/raniPush.exe` (single file, console, ±7,4 MB)
- Log agent: `C:\ProgramData\Rani\raniPush.log`
- Config agent: `C:\ProgramData\Rani\config.json` (berisi `agent_id` + signing key)
- Spool offline: `C:\ProgramData\Rani\spool\`

---

## 0. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| OS | Windows 10 / 11 (x64) |
| Hak akses | PowerShell **as Administrator** (untuk tulis `C:\ProgramData` + Task Scheduler) |
| Jaringan | Bisa reach `192.168.88.92:8091` (tes: `Test-NetConnection 192.168.88.92 -Port 8091`) |
| Token | Enrollment token dari UI RANI (sekali pakai, default berlaku 24 jam) |

Tidak perlu install Python, .NET, atau agent lain — exe sudah self-contained.

---

## 1. Ambil file exe ke laptop

Dari mesin Linux (server):

```bash
scp root@192.168.88.92:/root/RaniProject/ProjectDev/release/raniPush.exe .
```

Atau dari Windows (PowerShell), kalau SSH/scp tersedia:

```powershell
scp root@192.168.88.92:/root/RaniProject/ProjectDev/release/raniPush.exe "$env:USERPROFILE\Downloads\"
```

Alternatif tanpa SSH: copy lewat USB / share folder, atau unduh artefak dari
GitHub Actions workflow `build-agent-exe` bila repo sudah punya remote.

Cek file tidak korup (opsional tapi disarankan):

```powershell
Get-FileHash .\raniPush.exe -Algorithm SHA256
# bandingkan dengan hash yang diumumkan saat build, mis.
# 5af4ae09a4e678a92bed306029591b35a380a769246a65e998b643825d542a4e
```

Letakkan di folder kerja sementara, mis. `C:\Rani\raniPush.exe` (folder ini juga dipakai
oleh skrip installer).

---

## 2. Buat enrollment token di UI

1. Buka `http://192.168.88.92:8091` → login (`admin`).
2. Menu **Agents** → panel *Buat enrollment token*.
3. Isi **Label** (mis. `laptop-budi`) dan **TTL** (jam), klik **Buat**.
4. Token muncul **sekali** di alert hijau + perintah enroll siap-copy. Simpan sampai
   langkah 3 selesai.

Catatan: token sekali pakai. Kalau terlewat/kedaluwarsa, buat token baru — tidak masalah,
token lama tinggal tidak terpakai.

---

## 3. Enroll agent (sekali per PC)

PowerShell **as Administrator**, di folder tempat exe berada:

```powershell
cd C:\Rani
.\raniPush.exe --enroll <TOKEN> 192.168.88.92:8091
```

Contoh output sukses:

```
enrolled: agent_id=7cc9ff57-... server=http://192.168.88.92:8091 config=C:\ProgramData\Rani\config.json
```

Yang terjadi: token ditukar menjadi `agent_id` + **signing key**, lalu disimpan di
`C:\ProgramData\Rani\config.json`. File ini adalah kredensial agent —
**jangan dicopy ke PC lain** dan jangan di-commit ke git.

Kalau gagal:

| Pesan | Artinya |
|---|---|
| `token tidak dikenal` (401) | token salah ketik / bukan dari server ini |
| `token sudah dipakai` (409) | token dipakai PC lain → buat token baru |
| `token kedaluwarsa` (410) | lewat TTL → buat token baru |
| `Connection refused` / timeout | server tidak reachable → cek IP/port/firewall |

---

## 4. Push pertama (manual)

```powershell
.\raniPush.exe 192.168.88.92:8091
```

Output sukses:

```
push ok: report=39a25539-... asset=None next=3600s
```

- `exit code 0` = terkirim **atau** terspool (akan dicoba lagi otomatis).
- `exit code 1` = gagal fatal (biasanya belum enroll / config rusak).

Verifikasi di UI:

- `http://192.168.88.92:8091/assets` → hostname laptop muncul (badge **online**)
- Klik hostname → tab **Hardware / Software / Users / Security / Network** terisi
- Dashboard naik (total aset, top software, tren push)

Kalau PC ini sudah pernah dilaporkan, push berikutnya hanya mengirim **delta**
(software baru dihapus/dipasang), bukan snapshot ulang.

---

## 5. Jadwalkan otomatis (Task Scheduler)

### Opsi A — skrip installer (paling cepat)

Copy `scripts\install-agent.ps1` + `raniPush.exe` ke satu folder, lalu:

```powershell
.\install-agent.ps1 -Server 192.168.88.92:8091 -Token <TOKEN>
```

Skrip melakukan: copy exe ke `C:\Rani`, enroll, daftarkan task `RaniPush` (SYSTEM, tiap
60 menit), lalu push pertama. Tanpa `-Token` bila agent sudah pernah enroll.

### Opsi B — manual dengan schtasks

```powershell
schtasks /create /tn RaniPush /sc hourly /tr "C:\Rani\raniPush.exe 192.168.88.92:8091" /ru SYSTEM /rl HIGHEST /f
schtasks /run  /tn RaniPush
schtasks /query /tn RaniPush /v /fo LIST
```

Untuk interval lain (mis. 15 menit) gunakan Task Scheduler GUI → *Create Task* →
Triggers → *Repeat task every 15 minutes*.

Server bisa mengubah interval lewat field `next_interval_s` pada respons push; agent
menyimpannya dan memakai nilai itu pada run berikutnya (Task Scheduler tetap pemanggilnya,
jadi interval efektif = maksimum antara jadwal task dan nilai server).

---

## 6. Referensi CLI

| Perintah | Fungsi |
|---|---|
| `raniPush.exe` | collect + push memakai server yang tersimpan di config (kalau ada) |
| `raniPush.exe <server>` | collect + push ke server yang disebut (mode utama di Task Scheduler) |
| `raniPush.exe --collect` | cetak payload JSON ke stdout, **tidak** mengirim |
| `raniPush.exe --enroll <token> <server>` | tukar token → agent_id + signing key |
| `raniPush.exe --from-file <path> <server>` | kirim payload dari file (untuk uji/troubleshoot) |

`<server>` boleh `192.168.88.92` (port default 8091), `192.168.88.92:8091`, atau
`http://192.168.88.92:8091`.

Exit code: **0** = sukses/terspool, **1** = gagal fatal (enroll atau config bermasalah).
Kegagalan push (jaringan/401/422) **tidak** membuat exit 1: payload di-spool dan dicoba
lagi pada run berikutnya — detailnya ada di `raniPush.log`.

---

## 7. Data yang dikirim

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

## 8. Troubleshooting

Semua kejadian dicatat di `C:\ProgramData\Rani\raniPush.log`:

```powershell
Get-Content C:\ProgramData\Rani\raniPush.log -Tail 30
```

| Gejala | Cek / solusi |
|---|---|
| `push gagal (401)` | signing key tidak cocok: agent di-revoke atau config dari PC lain → enroll ulang dengan token baru. Selama belum di-enroll ulang, payload lama tetap di-spool (maks 7 hari) |
| `push gagal (409)` | nonce replay (jam PC mundur/DSN aneh) → sinkronkan waktu Windows: `w32tm /resync` |
| `push gagal (422)` | payload tidak lolos skema → kirim output `--collect` untuk diagnosa |
| `push gagal (429)` | terlalu sering push (>30/menit/agent) → naikkan interval task |
| `Connection refused` / `timed out` | server mati atau port diblokir: `Test-NetConnection 192.168.88.92 -Port 8091` |
| exit 1 tanpa pesan | jalankan manual di PowerShell (bukan lewat task) untuk melihat log |
| Hardware/software kosong | jalankan `--collect` lalu cek apakah PowerShell/WMI membatasi; jalankan sebagai admin/SYSTEM |
| `running scripts is disabled` | untuk skrip .ps1: `powershell -ExecutionPolicy Bypass -File .\install-agent.ps1 ...` |
| Task jalan tapi data tidak update | `schtasks /query /tn RaniPush /v /fo LIST` → lihat *Last Run Result* (0x0 = sukses) |

Reset enrollment (kalau config rusak / pindah server):

```powershell
Remove-Item C:\ProgramData\Rani\config.json
.\raniPush.exe --enroll <token-baru> 192.168.88.92:8091
```

Cabut akses PC (hilang/dicuri): UI **Agents** → tombol **Revoke**. Push berikutnya dari PC
tersebut akan ditolak 401.

---

## 9. Uninstall

```powershell
schtasks /delete /tn RaniPush /f
Remove-Item -Recurse -Force C:\Rani
Remove-Item -Recurse -Force C:\ProgramData\Rani
```

Setelah itu revoke agent-nya di UI supaya tidak tersisa sebagai agent aktif.

---

## 10. Kalau Windows memblokir `raniPush.exe` (SmartScreen / Smart App Control)

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
Get-Item .\raniPush.exe -Stream Zone.Identifier -ErrorAction SilentlyContinue

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

Tersedia `release/raniPush-signed.exe` (ditandatangani sertifikat code-signing internal
RANI + timestamp) dan `release/rani-push-signing.cer` (sertifikat publik).

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

`release/raniPush-portable.zip` berisi Python 3.13 embeddable resmi (python.exe
ditandatangani Python Software Foundation) + `raniPush.py` + `raniPush.cmd`. Tidak ada
binary buatan kita, jadi tidak ada yang bisa ditolak sebagai "untrusted exe".

```powershell
# extract dulu, mis. ke C:\Rani-portable
cd C:\Rani-portable
Unblock-File .\python\python.exe, .\raniPush.py, .\raniPush.cmd
.\raniPush.cmd --enroll <TOKEN> 192.168.88.92:8091
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

---

## 11. Cek cepat (cheat sheet)

```powershell
# 1. server hidup?
Test-NetConnection 192.168.88.92 -Port 8091

# 2. token baru di UI Agents, lalu:
cd C:\Rani
.\raniPush.exe --enroll <TOKEN> 192.168.88.92:8091
.\raniPush.exe 192.168.88.92:8091
Get-Content C:\ProgramData\Rani\raniPush.log -Tail 5

# 3. otomatiskan
.\install-agent.ps1 -Server 192.168.88.92:8091
```

Selesai — aset muncul di `http://192.168.88.92:8091/assets` dan ikut ter-update tiap
interval tanpa perlu scan jaringan atau kredensial domain.