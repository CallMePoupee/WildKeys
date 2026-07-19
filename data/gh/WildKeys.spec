# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — WildKeys app (onedir)

from pathlib import Path

ROOT = Path(SPECPATH)
ICON = str(ROOT / "ui" / "logo.ico")

hidden = [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "pynput._util.win32",
    "pystray._win32",
    "PIL._tkinter_finder",
    "paths",
    "worker",
    "hotkeys",
    "storage",
    "single_instance",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "ui"), "ui")],
    hiddenimports=hidden,
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
    [],
    exclude_binaries=True,
    name="WildKeys",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WildKeys",
)
