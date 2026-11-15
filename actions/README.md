# Folder Actions (dijalankan di PC pengguna)

Folder ini adalah **Action Path** bergaya Lansweeper: skrip/tool kecil yang bisa
dijalankan dari web RANI di PC orang yang sedang login (via handler `raniaction://`).

- Mount read-only ke container `api` (`./actions:/srv/actions:ro`).
- File yang boleh di-download & eksekusi klien: `.bat`, `.cmd`, `.ps1`, `.exe`, `.msi`.
- Dijalankan di PC pengguna, **bukan** di server. Args disubstitusi dari placeholder
  action (`{ipaddress}`, `{fqdn}`, `{mac}`, …) saat action diklik.
- Tidak ada credential yang tersimpan; klien mengunduh skrip lewat token HMAC yang
  berlaku 5 menit.

Lihat `handler/` untuk installer klien dan `docs/actions.md` §7 untuk tutorial lengkap.

## Contoh isi

| File | fungsi |
|---|---|
| `rdp.bat` | `mstsc /v:%1` — remote desktop ke asset |
| `ping.bat` | ping 4x |
| `compmgmt.bat` | `compmgmt.msc /computer=%1` — Computer Management remote |
| `services.bat` | `services.msc /computer=%1` — service console remote |
| `perfmon.bat` | `perfmon.msc /computer=%1` — performance monitor remote |
