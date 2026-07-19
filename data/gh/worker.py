"""
Hotkey worker process — isolated from the UI so keyboard hooks
never block the WebView message pump.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure imports work when launched as a script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from hotkeys import HotkeyEngine  # noqa: E402
from paths import data_dir  # noqa: E402
from storage import HOTKEY_STATUS, Store, write_status  # noqa: E402

STOP_PATH = data_dir() / "worker.stop"


def main() -> int:
    try:
        if STOP_PATH.exists():
            STOP_PATH.unlink()
    except OSError:
        pass

    store = Store()
    engine = HotkeyEngine(store)
    write_status("Worker starting…")

    try:
        engine.start()
    except Exception as exc:
        write_status(f"Hotkey error: {exc}")
        return 1

    write_status(HOTKEY_STATUS)

    # Light loop: pick up list edits + stop signal. Never touch the UI.
    while True:
        if STOP_PATH.exists():
            break
        try:
            store.reload_if_changed()
        except Exception:
            pass
        time.sleep(0.35)

    try:
        engine.stop()
    except Exception:
        pass
    write_status("Hotkeys stopped")
    return 0


if __name__ == "__main__":
    from single_instance import claim as _claim

    if not _claim("worker"):
        raise SystemExit(0)
    raise SystemExit(main())
