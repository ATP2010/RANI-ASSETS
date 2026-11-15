#!/usr/bin/env python3
"""Buat seluruh set ikon web RANI dari satu file PNG sumber.

Contoh:
    python3 scripts/make-icons.py ~/Downloads/logo-baru.png
    python3 scripts/make-icons.py logo.png --out server/app/static/img

Hasil (default ke server/app/static/img/):
    rani-logo-512.png        logo utama (512 px; halaman login + manifest)
    rani-adminlte-brand-160.png  logo sidebar AdminLTE (160 px, tampil ~33 px)
    favicon-32.png           ikon kecil (sidebar ringkas / favicon PNG 32)
    favicon-48.png           favicon PNG 48
    icon-192.png             ikon manifest (192)
    apple-touch-icon-180.png 180x180 untuk iOS
    favicon.ico              multi-ukuran 16/32/48

Syarat sumber: PNG (idealnya persegi, >= 512 px, latar transparan). Sumber
non-persegi akan dipad ke tengah dengan area transparan — tidak dipotong.

Butuh Pillow: pip install pillow (di host, bukan di container).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("ERROR: Pillow belum terpasang. Jalankan: pip install pillow")

PNG_SIZES = {"rani-logo-512.png": 512, "rani-adminlte-brand-160.png": 160,
             "favicon-32.png": 32, "favicon-48.png": 48,
             "icon-192.png": 192, "apple-touch-icon-180.png": 180}
ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


def square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ikon web RANI")
    parser.add_argument("source", help="file PNG sumber")
    parser.add_argument("--out", default="server/app/static/img",
                        help="direktori tujuan (default: server/app/static/img)")
    args = parser.parse_args()

    src_path = Path(args.source).expanduser()
    if not src_path.is_file():
        print(f"ERROR: {src_path} tidak ditemukan", file=sys.stderr)
        return 1
    try:
        src = Image.open(src_path).convert("RGBA")
    except OSError as exc:
        print(f"ERROR: {src_path} bukan gambar yang bisa dibaca ({exc})", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logo = square(src)
    print(f"sumber : {src_path} {src.size[0]}x{src.size[1]} → dipad {logo.size[0]}x{logo.size[1]}")
    print(f"tujuan : {out.resolve()}\n")

    for name, size in PNG_SIZES.items():
        img = logo.resize((size, size), Image.LANCZOS)
        path = out / name
        img.save(path, optimize=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(f"  {name:<22} {size:>3}x{size:<3} {path.stat().st_size:>8,} B  sha256:{digest}")

    ico = out / "favicon.ico"
    logo.save(ico, format="ICO", sizes=ICO_SIZES)
    digest = hashlib.sha256(ico.read_bytes()).hexdigest()[:12]
    print(f"  {'favicon.ico':<22} {'16/32/48':>7} {ico.stat().st_size:>8,} B  sha256:{digest}")

    print("\nLangkah berikutnya (dari root ProjectDev):")
    print("  docker compose build api")
    print("  docker compose create --force-recreate api")
    print("  docker compose start api")
    print("  curl -sS -o /dev/null -w '%{http_code} %{content_type}\\n' \\")
    print("    http://127.0.0.1:8091/static/img/favicon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())