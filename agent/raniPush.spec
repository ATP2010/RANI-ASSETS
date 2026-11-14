# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec untuk raniPush (Windows exe, single file, konsol).

Build di Windows:      pyinstaller agent/raniPush.spec --distpath release
Build di Linux/Wine:   bash scripts/build-exe.sh
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

a = Analysis(
    [str(ROOT / "raniPush.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "xmlrpc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="raniPush",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
)