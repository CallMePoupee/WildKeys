"""
WildKeys — UI process (no keyboard hooks here).
Hotkeys run in a separate worker.py process.
Close (X) hides to tray; minimize uses the taskbar as usual.
"""

from __future__ import annotations

import atexit
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview

from paths import data_dir, install_dir, is_frozen, resource_dir
from storage import (
    HOTKEY_STATUS,
    KEYS,
    Store,
    format_paste_line,
    read_status,
    write_status,
)

APP_DIR = install_dir()
UI_PATH = resource_dir() / "ui" / "index.html"
# Window taskbar, tray, and (when frozen) process icon source
ICON_PATH = resource_dir() / "ui" / "logo.ico"
WORKER_PATH = APP_DIR / "worker.py"
STOP_PATH = data_dir() / "worker.stop"


class Api:
    """
    JS bridge.

    IMPORTANT: only public *methods* may live without a leading underscore.
    pywebview walks public attributes and will try to expose nested objects
    like Store / Window / Tray — that breaks API injection ("bridge not ready").
    """

    def __init__(self) -> None:
        self._store = Store()
        self._worker: subprocess.Popen | None = None
        self._last_ui_status = "Ready"
        self._window: webview.Window | None = None
        self._tray: object | None = None
        self._maximized = False

    # ── window chrome (frameless custom title bar) ─────────
    def window_minimize(self) -> dict:
        if self._window is not None:
            try:
                self._window.minimize()
            except Exception:
                pass
        return {"ok": True}

    def window_toggle_maximize(self) -> dict:
        if self._window is None:
            return {"maximized": self._maximized}
        try:
            if self._maximized:
                self._window.restore()
                self._maximized = False
            else:
                self._window.maximize()
                self._maximized = True
        except Exception:
            pass
        return {"maximized": self._maximized}

    def window_close(self) -> dict:
        """Close (X) → tray, same as native close behavior."""
        tray = self._tray
        if tray is not None:
            try:
                tray.hide_to_tray()  # type: ignore[attr-defined]
            except Exception:
                pass
        elif self._window is not None:
            try:
                self._window.hide()
            except Exception:
                pass
        return {"ok": True}

    def window_is_maximized(self) -> dict:
        return {"maximized": self._maximized}

    def window_drag_start(self) -> dict:
        """Snapshot window position for custom title-bar dragging."""
        if self._window is None:
            return {"x": 0, "y": 0, "maximized": self._maximized}
        try:
            if self._maximized:
                try:
                    self._window.restore()
                except Exception:
                    pass
                self._maximized = False
            return {
                "x": int(self._window.x or 0),
                "y": int(self._window.y or 0),
                "maximized": self._maximized,
            }
        except Exception:
            return {"x": 0, "y": 0, "maximized": self._maximized}

    def window_drag_move(self, x: int, y: int) -> dict:
        if self._window is None:
            return {"ok": False}
        try:
            self._window.move(int(x), int(y))
            return {"ok": True}
        except Exception:
            return {"ok": False}

    def boot(self) -> dict:
        """Called once from JS when bridge is ready — keep this fast."""
        if self._store.is_enabled():
            self._last_ui_status = HOTKEY_STATUS
            self._ensure_worker_async()
        else:
            self._last_ui_status = "Hotkeys paused"
            write_status(self._last_ui_status)
        return self.get_state()

    def ping(self) -> dict:
        """Tiny health check used by the UI to confirm the bridge is live."""
        return {"ok": True, "ts": time.time()}

    def shutdown(self) -> None:
        self._stop_worker()

    def get_state(self) -> dict:
        """Deck metadata only (no full line payloads) for a fast bridge."""
        self._store.reload_if_changed()
        snap = self._store.snapshot()
        status = read_status()
        message = status.get("message") or self._last_ui_status

        cards = []
        for k in KEYS:
            item = snap["keys"][k]
            lines = item.get("lines") or []
            cards.append(
                {
                    "key": k,
                    "shortcut": f"Ctrl+Alt+{k.upper()}",
                    "label": item.get("label") or k.upper(),
                    "count": len(lines),
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return {
            "enabled": snap["enabled"],
            "status": message,
            "statusTs": status.get("ts") or 0,
            "revision": self._store.revision(),
            "hotkeysRunning": self._worker_alive(),
            "cards": cards,
        }

    def get_key(self, key: str) -> dict:
        """Full list body for one shortcut (lazy-loaded by the editor)."""
        key = str(key or "").lower()
        if key not in KEYS:
            return {
                "ok": False,
                "key": key,
                "label": "",
                "lines": [],
                "count": 0,
                "enabled": False,
            }
        self._store.reload_if_changed()
        snap = self._store.snapshot()
        item = snap["keys"][key]
        lines = list(item.get("lines") or [])
        return {
            "ok": True,
            "key": key,
            "shortcut": f"Ctrl+Alt+{key.upper()}",
            "label": item.get("label") or key.upper(),
            "lines": lines,
            "count": len(lines),
            "enabled": bool(item.get("enabled", True)),
        }

    def poll(self) -> dict:
        status = read_status()
        try:
            rev = self._store.path.stat().st_mtime
        except OSError:
            rev = 0
        enabled = True
        try:
            enabled = self._store.is_enabled()
        except Exception:
            pass
        return {
            "status": status.get("message") or self._last_ui_status,
            "statusTs": status.get("ts") or 0,
            "revision": rev,
            "enabled": enabled,
            "hotkeysRunning": self._worker_alive(),
            "paste": status.get("paste") or "",
            "pasteTs": status.get("paste_ts") or 0,
            "pasteKey": status.get("paste_key") or "",
        }

    def set_enabled(self, enabled: bool) -> dict:
        self._store.set_enabled(bool(enabled))
        if enabled:
            self._last_ui_status = HOTKEY_STATUS
            self._ensure_worker_async()
        else:
            self._last_ui_status = "Hotkeys paused"
        write_status(self._last_ui_status)
        return self.get_state()

    def save_key(self, key: str, label: str, text: str) -> dict:
        key = str(key or "").lower()
        if not str(label or "").strip():
            state = self.get_state()
            state["ok"] = False
            state["message"] = "Please enter a list name before saving."
            return state
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        try:
            self._store.update_key(key, label=label, lines=lines)
        except ValueError as exc:
            state = self.get_state()
            state["ok"] = False
            state["message"] = str(exc)
            return state
        self._last_ui_status = f"Saved · Ctrl+Alt+{str(key).upper()}"
        write_status(self._last_ui_status)
        state = self.get_state()
        detail = self.get_key(key)
        state["activeKey"] = detail
        state["ok"] = True
        return state

    def set_key_enabled(self, key: str, enabled: bool) -> dict:
        try:
            self._store.set_key_enabled(key, bool(enabled))
        except ValueError as exc:
            self._last_ui_status = str(exc)
            write_status(self._last_ui_status)
            state = self.get_state()
            state["ok"] = False
            state["message"] = str(exc)
            return state
        state_word = "on" if enabled else "off"
        self._last_ui_status = f"Ctrl+Alt+{str(key).upper()} · {state_word}"
        write_status(self._last_ui_status)
        state = self.get_state()
        state["ok"] = True
        return state

    def pick_preview(self, key: str) -> dict:
        self._store.reload_if_changed()
        lines = self._store.get_lines(key)
        if not lines:
            return {"ok": False, "text": "", "message": "List is empty"}
        text = random.choice(lines)
        return {"ok": True, "text": text, "message": "Preview pick"}

    def fire_hotkey(self, key: str) -> dict:
        key = str(key or "").lower()
        self._store.reload_if_changed()
        if key not in KEYS:
            return {"ok": False, "text": "", "message": "Unknown key"}
        if not self._store.is_enabled():
            return {"ok": False, "text": "", "message": "App paused (Armed off)"}
        if not self._store.is_key_enabled(key):
            return {"ok": False, "text": "", "message": "Shortcut disabled"}
        lines = [ln for ln in self._store.get_lines(key) if ln.strip()]
        if not lines:
            return {"ok": False, "text": "", "message": "Empty list"}
        text = format_paste_line(random.choice(lines))
        return {"ok": True, "text": text, "message": f"Ctrl+Alt+{key.upper()}"}

    def _worker_alive(self) -> bool:
        return self._worker is not None and self._worker.poll() is None

    def _ensure_worker_async(self) -> None:
        if self._worker_alive():
            return
        threading.Thread(target=self._ensure_worker, daemon=True).start()

    def _ensure_worker(self) -> None:
        if self._worker_alive():
            return
        try:
            if STOP_PATH.exists():
                STOP_PATH.unlink()
        except OSError:
            pass

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            if is_frozen():
                # Same packaged exe, worker entry via --worker
                cmd = [sys.executable, "--worker"]
            else:
                cmd = [sys.executable, str(WORKER_PATH)]
            self._worker = subprocess.Popen(
                cmd,
                cwd=str(APP_DIR),
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            write_status(HOTKEY_STATUS)
        except Exception as exc:
            self._worker = None
            write_status(f"Could not start worker: {exc}")

    def _stop_worker(self) -> None:
        try:
            STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
            STOP_PATH.write_text("1", encoding="utf-8")
        except OSError:
            pass

        proc = self._worker
        self._worker = None
        if proc is None:
            return
        try:
            proc.wait(timeout=0.8)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            if STOP_PATH.exists():
                STOP_PATH.unlink()
        except OSError:
            pass


class TrayController:
    """System tray: close-to-tray, restore, real quit."""

    def __init__(self, window: webview.Window, api: Api) -> None:
        self.window = window
        self.api = api
        self._icon = None
        self._thread: threading.Thread | None = None
        self._allow_close = False
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return

        try:
            if ICON_PATH.exists():
                image = Image.open(ICON_PATH).convert("RGBA")
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
            else:
                image = Image.new("RGBA", (64, 64), (196, 120, 90, 255))
        except Exception:
            image = Image.new("RGBA", (64, 64), (196, 120, 90, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Open WildKeys", self._on_show, default=True),
            pystray.MenuItem("Quit", self._on_quit),
        )
        self._icon = pystray.Icon("WildKeys", image, "WildKeys", menu)

        def run_icon() -> None:
            assert self._icon is not None
            self._icon.run()

        self._thread = threading.Thread(target=run_icon, daemon=True)
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        self._started = False

    def hide_to_tray(self) -> None:
        try:
            self.window.hide()
        except Exception:
            pass
        if not self._started:
            self.start()

    def show_window(self) -> None:
        try:
            self.window.show()
        except Exception:
            pass
        try:
            self.window.restore()
        except Exception:
            pass
        try:
            self.window.on_top = True
            self.window.on_top = False
        except Exception:
            pass

    def _on_show(self, _icon=None, _item=None) -> None:
        try:
            self.show_window()
        except Exception:
            pass

    def _on_quit(self, _icon=None, _item=None) -> None:
        self._allow_close = True
        self.stop()
        self.api.shutdown()
        try:
            self.window.destroy()
        except Exception:
            try:
                self.window.destroy()
            except Exception:
                pass
            import os

            os._exit(0)

    def handle_closing(self) -> bool:
        if self._allow_close:
            self.stop()
            self.api.shutdown()
            return True
        if not self._started:
            self.start()
        if not self._started:
            self.api.shutdown()
            return True
        self.hide_to_tray()
        return False


def main() -> int:
    if not UI_PATH.exists():
        print(f"UI missing: {UI_PATH}", file=sys.stderr)
        return 1

    try:
        if STOP_PATH.exists():
            STOP_PATH.unlink()
    except OSError:
        pass

    api = Api()
    atexit.register(api.shutdown)

    window = webview.create_window(
        title="WildKeys",
        url=UI_PATH.as_uri(),
        js_api=api,
        width=1200,
        height=720,
        min_size=(860, 600),
        background_color="#E6DED2",
        text_select=True,
        frameless=True,
        easy_drag=False,
    )

    tray = TrayController(window, api)
    # Private attrs only — pywebview must not walk these when building JS API
    api._window = window
    api._tray = tray

    def on_closing() -> bool:
        return tray.handle_closing()

    window.events.closing += on_closing

    def on_loaded() -> None:
        def _tray_later() -> None:
            time.sleep(0.4)
            try:
                tray.start()
            except Exception:
                pass

        threading.Thread(target=_tray_later, daemon=True).start()
        if api._store.is_enabled():
            api._ensure_worker_async()

    window.events.loaded += on_loaded

    start_kwargs: dict = {"debug": False}
    if ICON_PATH.exists():
        start_kwargs["icon"] = str(ICON_PATH)

    try:
        webview.start(gui="edgechromium", **start_kwargs)
    except Exception:
        webview.start(**start_kwargs)

    tray.stop()
    api.shutdown()
    return 0


if __name__ == "__main__":
    # Packaged builds re-launch this exe with --worker for the hotkey process.
    if "--worker" in sys.argv:
        from single_instance import claim as _claim
        from worker import main as worker_main

        if not _claim("worker"):
            raise SystemExit(0)
        raise SystemExit(worker_main())

    from single_instance import claim as _claim

    if not _claim("ui"):
        raise SystemExit(0)
    raise SystemExit(main())
