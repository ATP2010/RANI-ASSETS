# Branding: memasang logo / ikon aplikasi (manual)

Panduan mengganti ikon RANI — *Resource & Asset Network Intelligence* (favicon browser,
ikon install web app, logo sidebar dan halaman login). Semua ikon adalah file statis — **tidak ada upload lewat UI** dan tidak
ada setting di `.env`; yang berubah hanya file di `server/app/static/` lalu image
dibangun ulang.

## 0. File yang dipakai aplikasi

| File | Ukuran | Dipakai di |
|---|---|---|
| `server/app/static/img/favicon.ico` | 16/32/48 (multi) | tab browser, bookmark |
| `server/app/static/img/favicon-32.png` | 32x32 | `<link rel="icon">` modern + logo sidebar saat ringkas (class `logo-xs`) |
| `server/app/static/img/favicon-48.png` | 48x48 | `<link rel="icon" sizes="48x48">`, shortcut Windows |
| `server/app/static/img/icon-192.png` | 192x192 | manifest (install web app) |
| `server/app/static/img/rani-logo-512.png` | 512x512 | logo halaman login (96 px) + manifest |
| `server/app/static/img/apple-touch-icon-180.png` | 180x180 | iOS home screen |
| `server/app/static/img/rani-adminlte-brand-160.png` | 160x160 | logo brand sidebar AdminLTE (`brand-image`, tampil ~33 px) |
| `server/app/static/manifest.json` | — | nama `RANI — asset inventory`, `theme_color`, ikon 192/512 |

Template yang merujuk file tersebut: `server/app/templates/base.html` (head + brand
sidebar) dan `server/app/templates/login.html` (head + logo login).

## 1. Siapkan file sumber

- Format **PNG**, latar transparan disarankan.
- **Persegi** dan minimal **512x512**. Kalau tidak persegi, script akan memad ke tengah
  dengan area transparan (tidak memotong gambar).
- Ukuran wajar (< 1 MB). Hindari teks kecil — ikon 16 px tidak akan terbaca.

## 2. Generate semua ukuran (cara otomatis, disarankan)

Butuh Pillow di **host** (bukan di container), sekali saja:

```bash
pip install pillow        # atau: python3 -m pip install --user pillow
```

Lalu dari root `ProjectDev`:

```bash
python3 scripts/make-icons.py /path/ke/logo-baru.png
```

Contoh keluaran:

```
sumber : /root/logo-baru.png 1024x1024 → dipad 1024x1024
tujuan : /root/RaniProject/ProjectDev/server/app/static/img

  rani-logo-512.png       512x512  231,739 B  sha256:55f22b53dd6e
  rani-adminlte-brand-160.png 160x160   8,204 B  sha256:1fa84c2b10aa
  favicon-32.png           32x32     2,797 B  sha256:bee9f3f8a75e
  favicon-48.png           48x48     4,108 B  sha256:912cbd01f77c
  icon-192.png             192x192   48,561 B  sha256:135a6a3c114f
  apple-touch-icon-180.png  180x180   43,623 B  sha256:dd56e9863e4f
  favicon.ico              16/32/48    8,942 B  sha256:0cc02dd3271a
```

Catatan: `favicon.ico` dan `icon-192.png` di-generate dari `rani-logo-512.png`
(Pillow), jadi keduanya selalu konsisten dengan logo utama.

Script menimpa file lama dan bisa dijalankan berulang (idempoten). Opsi `--out` dipakai
kalau ingin menulis ke direktori lain lebih dulu untuk diperiksa.

## 3. Kalau mau manual (tanpa script)

Dengan ImageMagick:

```bash
SRC=logo-baru.png
TMP=$(mktemp -d)
convert "$SRC" -background none -gravity center -extent 1024x1024 "$TMP/sq.png"
cd /root/RaniProject/ProjectDev/server/app/static/img
convert "$TMP/sq.png" -resize 512x512 rani-logo-512.png
convert "$TMP/sq.png" -resize 160x160 rani-adminlte-brand-160.png
convert "$TMP/sq.png" -resize 32x32   favicon-32.png
convert "$TMP/sq.png" -resize 48x48   favicon-48.png
convert "$TMP/sq.png" -resize 192x192 icon-192.png
convert "$TMP/sq.png" -resize 180x180 apple-touch-icon-180.png
convert "$TMP/sq.png" -define icon:auto-resize=48,32,16 favicon.ico
```

Dengan Pillow (tanpa script repo):

```bash
python3 - <<'PY'
from PIL import Image
src = Image.open('logo-baru.png').convert('RGBA')
side = max(src.size)
sq = Image.new('RGBA', (side, side), (0, 0, 0, 0))
sq.paste(src, ((side - src.width) // 2, (side - src.height) // 2), src)
out = 'server/app/static/img/'
for name, px in {'rani-logo-512.png': 512, 'rani-adminlte-brand-160.png': 160,
                 'favicon-32.png': 32, 'favicon-48.png': 48,
                 'icon-192.png': 192, 'apple-touch-icon-180.png': 180}.items():
    sq.resize((px, px), Image.LANCZOS).save(out + name, optimize=True)
sq.save(out + 'favicon.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
PY
```

## 4. Template (hanya jika nama file berubah)

Sudah terpasang di `base.html`:

```html
<link rel="icon" href="/static/img/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/static/img/favicon-32.png">
<link rel="icon" type="image/png" sizes="48x48" href="/static/img/favicon-48.png">
<link rel="icon" type="image/png" sizes="192x192" href="/static/img/icon-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="/static/img/apple-touch-icon-180.png">
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#0d6efd" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#212529" media="(prefers-color-scheme: dark)">
```

Brand sidebar (logo besar + logo kecil saat ringkas):

```html
<a href="/" class="brand-link" title="RANI">
  <img src="/static/img/favicon-32.png" alt="" class="logo-xs brand-image-xs">
  <img src="/static/img/rani-adminlte-brand-160.png" alt="RANI" class="brand-image">
  <span class="brand-text fw-semibold">RANI</span>
</a>
```

`login.html` memakai blok `<link>` yang sama ditambah:

```html
<div class="login-logo">
  <img src="/static/img/rani-logo-512.png" alt="RANI" width="96" height="96" class="mb-2">
  <div><span class="fw-semibold">RANI</span> <span class="small-muted">asset inventory</span></div>
</div>
```

Kalau mengganti nama file, ubah juga `icons[].src` di `server/app/static/manifest.json`.
Kalau warna brand berubah, sesuaikan `theme_color` + `<meta name="theme-color">`.

## 5. Build ulang & restart

File statis ikut di-COPY ke image, jadi harus rebuild:

```bash
cd /root/RaniProject/ProjectDev
docker compose build api
docker compose create --force-recreate api
docker compose start api
curl -sS -m 8 http://127.0.0.1:8091/health      # {"status":"ok",...}
```

Jangan pakai `docker compose up` di sesi tooling (foreground) — pakai tiga perintah di atas.

## 6. Verifikasi

Cek setiap aset (harus 200 dengan content-type benar):

```bash
for f in img/favicon.ico img/favicon-32.png img/favicon-48.png \
         img/icon-192.png img/rani-logo-512.png img/rani-adminlte-brand-160.png \
         img/apple-touch-icon-180.png manifest.json; do
  curl -sS -o /dev/null -w "$f -> %{http_code} %{content_type} %{size_download}B\n" \
    "http://127.0.0.1:8091/static/$f"
done
```

Yang diharapkan:

| File | Content-type |
|---|---|
| `img/favicon.ico` | `image/vnd.microsoft.icon` |
| `img/*.png` | `image/png` |
| `manifest.json` | `application/json` |

Di browser:

1. Buka `http://192.168.88.92:8091/login` → logo tampil di atas judul.
2. **Ctrl+F5** (hard refresh) di dashboard → logo sidebar tampil; tab menampilkan ikon baru.
3. Klik ☰ → logo mengecil (28 px) tetap terlihat di sidebar ringkas.
4. DevTools → **Application → Manifest** → ikon 192/512 termuat, tanpa error.
5. Android/Chrome: menu → *Install app* memakai ikon 512.

## 7. Troubleshooting

| Gejala | Penyebab / solusi |
|---|---|
| Tab masih ikon lama | favicon di-cache keras. Ctrl+F5, buka tab baru, atau tutup semua tab domain ini. Chrome kadang perlu restart; cek `chrome://favicon` tidak bisa dipaksa — cukup tunggu/clear site data |
| `404` di `/static/img/...` | image belum dibuild ulang, atau nama file beda huruf besar/kecil (path case-sensitive di Linux) |
| Logo gepeng / terpotong | sumber non-persegi. Pakai `scripts/make-icons.py` (memad ke tengah), jangan resize manual tanpa `-extent` |
| Logo besar masih muncul saat sidebar ringkas | body harus punya `sidebar-mini` + `sidebar-collapse`; cek CSS `.sidebar-collapse ... .brand-image { display: none; }` |
| Logo kecil tidak muncul | elemen harus `class="logo-xs brand-image-xs"`; `.logo-xs` disembunyikan AdminLTE kecuali mode ringkas |
| Ikon PWA tidak berubah | web app lama menyimpan ikon. Uninstall lalu install ulang, atau DevTools → Application → *Clear storage* |
| iOS masih ikon lama di home screen | hapus shortcut, lalu *Add to Home Screen* lagi (iOS menyimpan snapshot) |
| `manifest.json` error di DevTools | JSON tidak valid atau `src` ikon salah; validasi: `python3 -m json.tool server/app/static/manifest.json` |

## 8. Checklist singkat

- [ ] Sumber PNG persegi >= 512 px tersedia
- [ ] `python3 scripts/make-icons.py <file>` sukses, 6 file tertulis
- [ ] `manifest.json` masih valid (`python3 -m json.tool`)
- [ ] `docker compose build api` → `create --force-recreate` → `start`
- [ ] `curl` semua aset = 200 + content-type benar
- [ ] Hard refresh: ikon tab, logo sidebar (buka & ringkas), logo login benar
- [ ] DevTools → Application → Manifest: ikon 192/512 termuat