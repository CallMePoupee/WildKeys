"""
WildKeys installer UI — extracts the packaged app and creates shortcuts.
Built as WildKeys-Setup.exe via build.bat.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import traceback
from pathlib import Path

import webview


def _payload_root() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        # Dev: installer/../dist/WildKeys
        base = Path(__file__).resolve().parent.parent / "dist" / "WildKeys"
        return base
    # Bundled as payload/*
    return base / "payload"


def default_install_dir() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local / "Programs" / "WildKeys"


def start_menu_dir() -> Path:
    programs = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return programs / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def create_shortcut(lnk_path: Path, target: Path, workdir: Path, icon: Path, desc: str) -> None:
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(lnk_path))
        shortcut.Targetpath = str(target)
        shortcut.WorkingDirectory = str(workdir)
        shortcut.IconLocation = str(icon)
        shortcut.Description = desc
        shortcut.save()
        return
    except Exception:
        pass

    # Fallback: PowerShell COM via temp script (reliable quoting)
    import subprocess
    import tempfile

    script = (
        f"$ws = New-Object -ComObject WScript.Shell\n"
        f"$s = $ws.CreateShortcut({_ps_quote(str(lnk_path))})\n"
        f"$s.TargetPath = {_ps_quote(str(target))}\n"
        f"$s.WorkingDirectory = {_ps_quote(str(workdir))}\n"
        f"$s.IconLocation = {_ps_quote(str(icon))}\n"
        f"$s.Description = {_ps_quote(desc)}\n"
        f"$s.Save()\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(script)
        ps1 = fh.name
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                ps1,
            ],
            check=False,
            capture_output=True,
        )
    finally:
        try:
            os.unlink(ps1)
        except OSError:
            pass


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_uninstall(install_dir: Path) -> None:
    uninst = install_dir / "Uninstall WildKeys.bat"
    uninst.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "INST={install_dir}"',
                'echo Uninstalling WildKeys...',
                'taskkill /IM WildKeys.exe /F >nul 2>&1',
                'timeout /t 1 /nobreak >nul',
                'del /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\WildKeys.lnk" >nul 2>&1',
                'del /q "%USERPROFILE%\\Desktop\\WildKeys.lnk" >nul 2>&1',
                'rmdir /s /q "%INST%"',
                "echo Done. Your lists in %%LOCALAPPDATA%%\\WildKeys were kept.",
                "pause",
                "endlocal",
                "",
            ]
        ),
        encoding="utf-8",
    )


class InstallApi:
    def __init__(self) -> None:
        self._busy = False
        self._last_error = ""

    def get_defaults(self) -> dict:
        d = default_install_dir()
        return {
            "installDir": str(d),
            "desktopShortcut": True,
            "startMenuShortcut": True,
            "launchAfter": True,
        }

    def browse_folder(self, current: str = "") -> dict:
        """Native folder picker; returns chosen path or empty if cancelled."""
        start = (current or "").strip()
        if not start or not Path(start).exists():
            start = str(default_install_dir().parent)
        try:
            if webview.windows:
                result = webview.windows[0].create_file_dialog(
                    webview.FOLDER_DIALOG,
                    directory=start,
                )
                if result and len(result) > 0:
                    chosen = Path(result[0])
                    # Install into a WildKeys subfolder when a parent is picked
                    if chosen.name.lower() != "wildkeys":
                        chosen = chosen / "WildKeys"
                    return {"ok": True, "path": str(chosen)}
                return {"ok": True, "path": ""}
        except Exception:
            pass
        # Fallback: tkinter
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(initialdir=start, title="Choose install folder")
            root.destroy()
            if path:
                chosen = Path(path)
                if chosen.name.lower() != "wildkeys":
                    chosen = chosen / "WildKeys"
                return {"ok": True, "path": str(chosen)}
            return {"ok": True, "path": ""}
        except Exception as exc:
            return {"ok": False, "path": "", "message": str(exc)}

    def install(self, install_dir: str, desktop: bool, start_menu: bool, launch: bool) -> dict:
        if self._busy:
            return {"ok": False, "message": "Install already running"}
        self._busy = True
        self._last_error = ""
        try:
            target = Path(install_dir.strip() or str(default_install_dir()))
            src = _payload_root()
            if not src.exists():
                raise FileNotFoundError(f"Installer payload missing:\n{src}")

            exe_src = src / "WildKeys.exe"
            if not exe_src.exists():
                raise FileNotFoundError(f"WildKeys.exe not in payload:\n{src}")

            target.mkdir(parents=True, exist_ok=True)

            # Copy tree (replace previous install)
            for item in src.iterdir():
                dest = target / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            exe = target / "WildKeys.exe"
            icon = target / "_internal" / "ui" / "logo.ico"
            if not icon.exists():
                icon = target / "ui" / "logo.ico"
            if not icon.exists():
                icon = exe

            write_uninstall(target)

            if start_menu:
                sm = start_menu_dir()
                sm.mkdir(parents=True, exist_ok=True)
                create_shortcut(
                    sm / "WildKeys.lnk",
                    exe,
                    target,
                    icon,
                    "WildKeys",
                )

            if desktop:
                create_shortcut(
                    desktop_dir() / "WildKeys.lnk",
                    exe,
                    target,
                    icon,
                    "WildKeys",
                )

            if launch:
                try:
                    os.startfile(str(exe))  # type: ignore[attr-defined]
                except Exception:
                    pass

            return {
                "ok": True,
                "message": f"Installed to:\n{target}",
                "installDir": str(target),
            }
        except Exception as exc:
            self._last_error = f"{exc}\n{traceback.format_exc()}"
            return {"ok": False, "message": str(exc)}
        finally:
            self._busy = False

    def quit(self) -> None:
        for w in webview.windows:
            try:
                w.destroy()
            except Exception:
                pass


INSTALL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Install WildKeys</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: #e6ded2;
      --bg-deep: #d9d0c2;
      --surface: #f0e9df;
      --surface-2: #f7f1e8;
      --ink: #2f2a26;
      --ink-soft: #5c534c;
      --ink-mute: #8a7f74;
      --line: #3a332e;
      --shadow: rgba(196, 183, 166, 0.5);
      --accent: #c4785a;
      --ok: #5d8a6a;
      --danger: #b45a4e;
      --border: 2.5px solid var(--line);
      --font: "Outfit", "Segoe UI", system-ui, sans-serif;
      --ease: cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; height: 100%;
      font-family: var(--font);
      background: var(--bg);
      color: var(--ink);
      overflow: hidden;
      user-select: none;
      -webkit-font-smoothing: antialiased;
    }
    body {
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(196, 120, 90, 0.12), transparent 55%),
        radial-gradient(900px 500px at 100% 0%, rgba(111, 143, 122, 0.10), transparent 50%),
        linear-gradient(165deg, #ebe3d7 0%, #e0d6c8 48%, #d9d0c2 100%);
    }
    button, input { font: inherit; color: inherit; }
    button {
      cursor: pointer;
      border: none;
      background: none;
    }
    .shell {
      height: 100%;
      display: flex;
      flex-direction: column;
      padding: 20px 22px 16px;
      overflow: hidden;
    }
    h1 {
      margin: 0 0 4px;
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }
    .by {
      margin: 0 0 14px;
      color: var(--ink-mute);
      font-size: 0.82rem;
      font-weight: 500;
    }
    .card {
      background: var(--surface);
      border: var(--border);
      box-shadow: 4px 4px 0 var(--shadow);
      border-radius: 14px;
      /* Equal inset above Install folder and below action buttons */
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      flex-shrink: 0;
    }
    label.field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: -0.01em;
      color: var(--ink-soft);
    }
    .path-row {
      display: flex;
      gap: 8px;
      align-items: stretch;
    }
    .path-row input[type=text] {
      flex: 1;
      min-width: 0;
    }
    input[type=text] {
      font-weight: 500;
      padding: 10px 12px;
      border: var(--border);
      border-radius: 10px;
      background: var(--surface-2);
      color: var(--ink);
      outline: none;
      box-shadow: 2px 2px 0 var(--shadow);
    }
    input[type=text]:focus { border-color: var(--accent); }
    .checks {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 2px;
    }
    /* Option row: label + switch only (no pill card around the line) */
    .opt {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      user-select: none;
      cursor: pointer;
      padding: 2px 0;
    }
    .opt-label {
      font-size: 0.9rem;
      font-weight: 500;
      letter-spacing: -0.01em;
      color: var(--ink);
    }
    .opt input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }
    /* Switch matches app track/thumb, sits outside any line card */
    .toggle-track {
      width: 42px;
      height: 24px;
      border-radius: 999px;
      border: 2px solid var(--line);
      background: var(--bg-deep);
      position: relative;
      flex-shrink: 0;
      box-shadow: 2px 2px 0 var(--shadow);
      transition: background 0.2s var(--ease), filter 0.15s var(--ease);
    }
    .opt:hover .toggle-track {
      filter: brightness(0.97);
    }
    .opt:active .toggle-track {
      filter: brightness(0.93);
    }
    .toggle-thumb {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: var(--surface-2);
      border: 2px solid var(--line);
      transition: transform 0.2s var(--ease), background 0.2s var(--ease);
    }
    .opt input:checked + .toggle-track {
      background: #c9dccf;
    }
    .opt input:checked + .toggle-track .toggle-thumb {
      transform: translateX(18px);
      background: var(--ok);
      border-color: #3d5c46;
    }
    /* Always reserve room so "Installing…" / "Installed to…" fit without
       eating the card's bottom padding */
    .msg {
      display: block;
      min-height: 2.9em;
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--ink-mute);
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.35;
      margin-top: 4px;
    }
    .msg:empty { color: transparent; }
    .msg.err { color: var(--danger); }
    .msg.ok { color: var(--ok); }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 14px;
    }
    .btn {
      border: var(--border);
      border-radius: 10px;
      padding: 10px 16px;
      font-weight: 650;
      font-size: 0.84rem;
      letter-spacing: -0.01em;
      box-shadow: 3px 3px 0 var(--shadow);
      transition: background 0.15s var(--ease), filter 0.15s var(--ease);
      flex: 0 0 auto;
      width: fit-content;
      min-width: fit-content;
      max-width: none;
      white-space: nowrap;
      color: var(--ink);
    }
    .btn:hover:not(:disabled) {
      filter: brightness(0.97);
    }
    .btn:active:not(:disabled) {
      filter: brightness(0.93);
    }
    .btn:disabled {
      opacity: 0.45;
      cursor: default;
      box-shadow: 2px 2px 0 var(--shadow);
      filter: none;
    }
    .btn.ghost {
      background: var(--surface-2);
    }
    .btn.primary {
      background: #d4a08c;
      color: var(--ink);
      transition:
        background 0.15s var(--ease),
        filter 0.15s var(--ease);
    }
    .btn.primary:hover:not(:disabled) {
      background: #c9917a;
      filter: none;
    }
    .btn.browse {
      padding: 10px 14px;
      background: var(--surface-2);
    }
  </style>
</head>
<body>
  <div class="shell">
    <h1>Install WildKeys</h1>
    <p class="by">by Charlotte Chapdelaine</p>
    <div class="card">
      <label class="field">
        Install folder
        <div class="path-row">
          <input type="text" id="dir" spellcheck="false" />
          <button type="button" class="btn browse" id="browse">Browse…</button>
        </div>
      </label>
      <div class="checks">
        <label class="opt">
          <span class="opt-label">Create a Start Menu shortcut</span>
          <input type="checkbox" id="startMenu" checked />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
        </label>
        <label class="opt">
          <span class="opt-label">Put a shortcut on the desktop</span>
          <input type="checkbox" id="desktop" checked />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
        </label>
        <label class="opt">
          <span class="opt-label">Launch WildKeys when it's finished installing</span>
          <input type="checkbox" id="launch" checked />
          <span class="toggle-track"><span class="toggle-thumb"></span></span>
        </label>
      </div>
      <div class="actions">
        <button type="button" class="btn ghost" id="cancel">Cancel</button>
        <button type="button" class="btn primary" id="install">Install</button>
      </div>
      <div class="msg" id="msg" aria-live="polite"></div>
    </div>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    const msg = $("msg");
    const installBtn = $("install");
    const cancelBtn = $("cancel");

    function setMsg(text, mode) {
      msg.textContent = text || "";
      msg.className = "msg" + (mode && text ? " " + mode : "");
    }

    function setButtonLabel(btn, label) {
      // Clear any fixed size so the control can reflow to the new caption
      btn.style.width = "";
      btn.style.minWidth = "";
      btn.textContent = label;
      // Force layout so WebView2 measures the new text
      void btn.offsetWidth;
      btn.style.width = "fit-content";
      btn.style.minWidth = "fit-content";
    }

    async function api(method, ...args) {
      for (let i = 0; i < 80; i++) {
        const a = window.pywebview && window.pywebview.api;
        if (a && typeof a[method] === "function") return a[method](...args);
        await new Promise((r) => setTimeout(r, 50));
      }
      throw new Error("Installer bridge not ready");
    }

    async function boot() {
      try {
        const d = await api("get_defaults");
        $("dir").value = d.installDir || "";
        $("desktop").checked = !!d.desktopShortcut;
        $("startMenu").checked = !!d.startMenuShortcut;
        $("launch").checked = !!d.launchAfter;
      } catch (e) {
        setMsg(String(e.message || e), "err");
      }
    }

    $("browse").onclick = async () => {
      try {
        const res = await api("browse_folder", $("dir").value);
        if (res && res.path) {
          $("dir").value = res.path;
        } else if (res && res.ok === false && res.message) {
          setMsg(res.message, "err");
        }
      } catch (e) {
        setMsg(String(e.message || e), "err");
      }
    };

    $("cancel").onclick = () => { api("quit").catch(() => window.close()); };
    $("install").onclick = async () => {
      installBtn.disabled = true;
      setMsg("Installing…");
      try {
        const res = await api(
          "install",
          $("dir").value,
          $("desktop").checked,
          $("startMenu").checked,
          $("launch").checked
        );
        if (res && res.ok) {
          setMsg(res.message || "Installed.", "ok");
          setButtonLabel(installBtn, "Installed");
          setButtonLabel(cancelBtn, "Close");
          installBtn.disabled = true;
        } else {
          setMsg((res && res.message) || "Install failed", "err");
          installBtn.disabled = false;
        }
      } catch (e) {
        setMsg(String(e.message || e), "err");
        installBtn.disabled = false;
      }
    };

    window.addEventListener("pywebviewready", boot);
    boot();
  </script>
</body>
</html>
"""


def main() -> int:
    api = InstallApi()
    # Write HTML next to runtime for file:// load reliability
    if getattr(sys, "frozen", False):
        html_path = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "install.html"
    else:
        html_path = Path(__file__).with_name("install.html")
    html_path.write_text(INSTALL_HTML, encoding="utf-8")

    icon = None
    for candidate in (
        _payload_root() / "_internal" / "ui" / "logo.ico",
        _payload_root() / "ui" / "logo.ico",
        Path(__file__).resolve().parent.parent / "ui" / "logo.ico",
    ):
        if candidate.exists():
            icon = str(candidate)
            break

    webview.create_window(
        "Install WildKeys",
        url=html_path.as_uri(),
        js_api=api,
        width=520,
        height=500,
        resizable=False,
        background_color="#E6DED2",
        text_select=False,
    )
    kwargs = {"gui": "edgechromium", "debug": False}
    if icon:
        kwargs["icon"] = icon
    try:
        webview.start(**kwargs)
    except Exception:
        webview.start(debug=False, icon=icon) if icon else webview.start(debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
