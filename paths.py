"""App paths for dev vs frozen (PyInstaller) installs."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Bundled read-only assets (ui/, etc.)."""
    if is_frozen():
        # PyInstaller onedir/onefile extract / _internal
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def install_dir() -> Path:
    """Directory containing the main executable (or project root in dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """
    Writable runtime data (lists, status, locks).

    Frozen installs use %LOCALAPPDATA%\\WildKeys so Program Files stays read-only.
    Dev uses <project>/data.
    """
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        path = base / "WildKeys"
    else:
        path = install_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path
