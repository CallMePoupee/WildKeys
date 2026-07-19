"""Global hotkeys and random line paste (runs in worker process only)."""

from __future__ import annotations

import random
import sys
import threading
import time
from typing import Callable

import pyperclip
from pynput.keyboard import Controller, GlobalHotKeys, Key

from storage import HOTKEY_STATUS, KEYS, Store, format_paste_line, write_status

StatusCallback = Callable[[str], None]


def _win_send_ctrl_v() -> bool:
    """Send Ctrl+V via Win32 keybd_event (more reliable than pynput into many apps)."""
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_V = 0x56
        # Ensure modifiers from the hotkey chord are released first
        for vk in (0x11, 0x12, 0x10):  # Ctrl, Alt, Shift
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


def _is_wildkeys_foreground() -> bool:
    """True when the WildKeys window is focused (in-app testing)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        length = int(user32.GetWindowTextLengthW(hwnd))
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip().lower()
        return "wildkeys" in title
    except Exception:
        return False


class HotkeyEngine:
    """Listens for Ctrl+Alt+Q W R T Y U I D G K and pastes a random line."""

    def __init__(
        self,
        store: Store,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.store = store
        self.on_status = on_status
        self._controller = Controller()
        self._listener: GlobalHotKeys | None = None
        self._lock = threading.Lock()
        self._busy = False
        self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            mapping = {f"<ctrl>+<alt>+{k}": self._make_handler(k) for k in KEYS}
            self._listener = GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            self._running = True
            self._notify(HOTKEY_STATUS)

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
            self._running = False
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        self._notify("Hotkeys paused")

    def is_running(self) -> bool:
        return self._running

    def _make_handler(self, key: str) -> Callable[[], None]:
        def handler() -> None:
            threading.Thread(target=self._fire, args=(key,), daemon=True).start()

        return handler

    def _fire(self, key: str) -> None:
        self.store.reload_if_changed()

        if not self.store.is_enabled():
            self._notify(f"Ctrl+Alt+{key.upper()} ignored · app paused")
            return

        if not self.store.is_key_enabled(key):
            self._notify(f"Ctrl+Alt+{key.upper()} ignored · shortcut off")
            return

        with self._lock:
            if self._busy:
                return
            self._busy = True

        try:
            lines = [ln for ln in self.store.get_lines(key) if ln.strip()]
            if not lines:
                self._notify(f"Ctrl+Alt+{key.upper()} · empty list")
                return

            text = format_paste_line(random.choice(lines))
            preview = text if len(text) <= 48 else text[:45] + "…"
            # Exactly one paste path:
            # - WildKeys focused → UI inject only (WebView ignores synthetic Ctrl+V)
            # - Other app focused → OS Ctrl+V only (no UI inject payload)
            if _is_wildkeys_foreground():
                self._notify(
                    f"Ctrl+Alt+{key.upper()} → {preview}",
                    extra={
                        "paste": text,
                        "paste_ts": time.time(),
                        "paste_key": key,
                    },
                )
            else:
                time.sleep(0.25)
                ok = self._paste_text(text)
                if ok:
                    self._notify(f"Ctrl+Alt+{key.upper()} → {preview}")
                else:
                    self._notify(f"Ctrl+Alt+{key.upper()} · paste failed")
        finally:
            with self._lock:
                self._busy = False

    def _paste_text(self, text: str) -> bool:
        """Clipboard + Ctrl+V. Always leave text on clipboard briefly for WebView fallback."""
        try:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None

            pyperclip.copy(text)
            time.sleep(0.06)

            if sys.platform == "win32":
                ok = _win_send_ctrl_v()
            else:
                ok = False

            if not ok:
                # Fallback: pynput
                try:
                    kb = self._controller
                    for k in (Key.ctrl, Key.alt, Key.shift):
                        try:
                            kb.release(k)
                        except Exception:
                            pass
                    time.sleep(0.02)
                    kb.press(Key.ctrl)
                    kb.press("v")
                    kb.release("v")
                    kb.release(Key.ctrl)
                    ok = True
                except Exception:
                    ok = False

            if previous is not None:

                def restore() -> None:
                    # Longer delay so in-app / slow targets can still paste
                    time.sleep(0.9)
                    try:
                        pyperclip.copy(previous)
                    except Exception:
                        pass

                threading.Thread(target=restore, daemon=True).start()
            return ok
        except Exception:
            return False

    def _notify(self, message: str, extra: dict | None = None) -> None:
        write_status(message, extra=extra)
        if self.on_status:
            try:
                self.on_status(message)
            except Exception:
                pass
