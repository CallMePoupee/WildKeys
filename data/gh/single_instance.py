"""Single-instance guard (Windows file lock + named mutex)."""

from __future__ import annotations

import sys
from pathlib import Path

from paths import data_dir

LOCK_DIR = data_dir()

# Keep lock resources alive for process lifetime
_fps: list = []
_handles: list = []


def claim(name: str) -> bool:
    """Return True if this process owns the instance."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f".{name}.lock"

    # 1) Exclusive file lock (works well on Windows)
    try:
        fp = open(lock_path, "a+b")
        fp.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fp.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fp.close()
                return False
        fp.write(str(os_getpid()).encode("ascii", "ignore") + b"\n")
        fp.flush()
        _fps.append(fp)
    except OSError:
        # Fall through to mutex
        pass
    else:
        # Also take a named mutex as a second belt
        _claim_mutex(name)
        return True

    return _claim_mutex(name)


def os_getpid() -> int:
    import os

    return os.getpid()


def _claim_mutex(name: str) -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, True, f"Local\\WildKeys_{name}_v3")
        if not handle:
            return True
        err = kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _handles.append(handle)
        return True
    except Exception:
        return True
