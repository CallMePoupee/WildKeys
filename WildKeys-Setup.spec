# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — WildKeys-Setup.exe (onefile installer with app payload)

from pathlib import Path

ROOT = Path(SPECPATH)
ICON = str(ROOT / "ui" / "logo.ico")
PAYLOAD = ROOT / "dist" / "WildKeys"

a = Analysis(
    [str(ROOT / "installer" / "setup_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(PAYLOAD), "payload"),
        (str(ROOT / "ui" / "logo.ico"), "."),
    ],
    hiddenimports=[
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WildKeys-Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
