"""
Command router — receives a parsed intent dict from brain.py and
dispatches it to the correct OS handler.

Handlers are registered in _HANDLERS at the bottom of the file.
Each handler receives (action: str, params: dict) and returns
{"success": bool, "output": str, "error": str}.

Optional deps (pyautogui, pytesseract) are imported lazily so the
app still starts even if they're not installed — those intents will
return a clear "not available" error rather than crashing.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from config.settings import config
from core import computer_control as cc

_OS = platform.system().lower()   # "windows" | "darwin" | "linux"


# ── Result helpers ────────────────────────────────────────────────────────────

def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}

def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_open_app(action: str, params: dict) -> dict:
    app = params.get("app_name", "")
    url = params.get("url", "")

    if action == "open_url" or url:
        webbrowser.open(url or app)
        return _ok(f"Opened URL: {url or app}")

    if action == "open_browser":
        browser = params.get("browser", "").lower()
        browsers = {"chrome": "chrome", "firefox": "firefox", "edge": "msedge"}
        exe = browsers.get(browser, "")
        if exe and shutil.which(exe):
            subprocess.Popen([exe])
        else:
            webbrowser.open("about:blank")
        return _ok(f"Opened {browser or 'default browser'}")

    # Generic app open
    name = app or action.replace("open_", "")
    if not name:
        return _err("No app name provided")

    if _OS == "windows":
        try:
            os.startfile(name)
            return _ok(f"Launched {name}")
        except Exception:
            pass
        # Try as executable name
        if shutil.which(name):
            subprocess.Popen([name])
            return _ok(f"Launched {name}")
    else:
        if shutil.which(name):
            subprocess.Popen([name])
            return _ok(f"Launched {name}")

    return _err(f"Could not find application: {name}")


def _handle_close_app(action: str, params: dict) -> dict:
    name = params.get("app_name", params.get("process_name", ""))
    if not name:
        return _err("No app name provided")

    if _OS == "windows":
        result = subprocess.run(
            ["taskkill", "/F" if action == "force_quit" else "/IM", f"{name}.exe"],
            capture_output=True, text=True
        )
        return _ok(result.stdout) if result.returncode == 0 else _err(result.stderr)
    else:
        flag = "-9" if action == "force_quit" else "-15"
        result = subprocess.run(["pkill", flag, name], capture_output=True, text=True)
        return _ok() if result.returncode == 0 else _err(f"Process not found: {name}")


def _handle_search_web(action: str, params: dict) -> dict:
    query = params.get("query", "")
    platform_key = params.get("platform", "google")

    urls = {
        "google":       f"https://www.google.com/search?q={query.replace(' ', '+')}",
        "youtube":      f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
        "github":       f"https://github.com/search?q={query.replace(' ', '+')}",
        "stackoverflow": f"https://stackoverflow.com/search?q={query.replace(' ', '+')}",
        "wikipedia":    f"https://en.wikipedia.org/wiki/Special:Search?search={query.replace(' ', '_')}",
    }
    url = urls.get(platform_key, urls["google"])
    webbrowser.open(url)
    return _ok(f"Searching {platform_key} for: {query}")


def _handle_type_text(action: str, params: dict) -> dict:
    if action == "press_key":
        return cc.press_key(params.get("key", ""))
    text = params.get("text", "")
    if action == "type_paste":
        r = cc.set_clipboard(text)
        return r if not r["success"] else cc.press_key("ctrl+v")
    return cc.type_text(text, float(params.get("delay", 0.02)))


def _handle_control_mouse(action: str, params: dict) -> dict:
    x, y = params.get("x"), params.get("y")
    if action == "move_mouse":
        return cc.move(x, y)
    if action == "click":
        return cc.click(x, y, params.get("button", "left"))
    if action == "double_click":
        return cc.double_click(x, y)
    if action == "right_click":
        return cc.right_click(x, y)
    if action == "scroll":
        return cc.scroll(params.get("direction", "up"), int(params.get("amount", 3)))
    if action == "drag":
        return cc.drag(params["from_x"], params["from_y"], params["to_x"], params["to_y"])
    return _err(f"Unknown mouse action: {action}")


def _handle_system_control(action: str, params: dict) -> dict:
    if action in ("volume_up", "volume_down", "volume_mute"):
        return cc.set_volume(action)

    if action == "screenshot":
        return cc.screenshot(path=params.get("save_path") or None)

    if action == "lock_screen":
        return cc.lock_screen()

    if action in ("shutdown", "restart", "sleep"):
        cmds = {
            "windows": {"shutdown": ["shutdown", "/s", "/t", "5"],
                        "restart":  ["shutdown", "/r", "/t", "5"],
                        "sleep":    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]},
            "darwin":  {"shutdown": ["sudo", "shutdown", "-h", "now"],
                        "restart":  ["sudo", "shutdown", "-r", "now"],
                        "sleep":    ["pmset", "sleepnow"]},
            "linux":   {"shutdown": ["shutdown", "-h", "now"],
                        "restart":  ["shutdown", "-r", "now"],
                        "sleep":    ["systemctl", "suspend"]},
        }
        cmd = cmds.get(_OS, cmds["linux"]).get(action)
        if cmd:
            subprocess.Popen(cmd)
        return _ok(f"Executing: {action}")

    return _ok(f"System: {action}")


def _handle_file_operation(action: str, params: dict) -> dict:
    path = Path(params.get("path", "")).expanduser()
    dest = Path(params.get("destination", "")).expanduser() if params.get("destination") else None

    if action == "create_file":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(params.get("content", ""), encoding="utf-8")
        return _ok(f"Created: {path}")

    if action == "read_file":
        if not path.exists():
            return _err(f"File not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return _ok(content[:2000])  # cap output

    if action == "delete_file":
        if not path.exists():
            return _err(f"Not found: {path}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return _ok(f"Deleted: {path}")

    if action == "move_file":
        if dest is None:
            return _err("No destination provided")
        shutil.move(str(path), str(dest))
        return _ok(f"Moved {path} → {dest}")

    if action == "copy_file":
        if dest is None:
            return _err("No destination provided")
        shutil.copy2(str(path), str(dest))
        return _ok(f"Copied {path} → {dest}")

    if action == "list_directory":
        if not path.exists():
            return _err(f"Directory not found: {path}")
        entries = [str(p.name) for p in sorted(path.iterdir())]
        return _ok("\n".join(entries[:100]))

    if action == "search_files":
        pattern = params.get("pattern", "*")
        base = path if path.is_dir() else Path.home()
        results = [str(p) for p in base.rglob(pattern)][:50]
        return _ok("\n".join(results) if results else "No matches found")

    return _err(f"Unknown file action: {action}")


def _handle_code_execution(action: str, params: dict) -> dict:
    code = params.get("code", params.get("script_path", ""))
    cwd  = params.get("working_directory", None)

    if not code:
        return _err("No code or command provided")

    if action == "run_python":
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, cwd=cwd
        )
        out = result.stdout or result.stderr
        return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])

    if action in ("run_shell", "git_command", "npm_command"):
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=60, cwd=cwd, shell=False
            )
            out = (result.stdout or result.stderr or "").strip()
            return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])
        except subprocess.TimeoutExpired:
            return _err("Command timed out after 60s")

    if action == "run_script":
        path = Path(code).expanduser()
        if not path.exists():
            return _err(f"Script not found: {path}")
        result = subprocess.run(
            [sys.executable, str(path)] if path.suffix == ".py" else [str(path)],
            capture_output=True, text=True, timeout=60, cwd=cwd
        )
        return _ok(result.stdout[:2000]) if result.returncode == 0 else _err(result.stderr[:2000])

    return _err(f"Unknown code action: {action}")


def _handle_browser_automation(action: str, params: dict) -> dict:
    url = params.get("url", "")
    if action in ("navigate", "new_tab") and url:
        webbrowser.open(url)
        return _ok(f"Navigated to {url}")
    # Full browser automation (click_element, fill_form) needs playwright/selenium
    return _ok(f"Browser: {action} (basic navigation only in this build)")


def _handle_read_screen(action: str, params: dict) -> dict:
    region = params.get("region") if action == "ocr_region" else None
    return cc.ocr_screen(region=region)


def _handle_automation_task(action: str, params: dict) -> dict:
    steps = params.get("steps", [])
    if not steps:
        return _err("No steps provided in automation task")

    results = []
    for i, step in enumerate(steps, 1):
        sub = dispatch({
            "intent":     step.get("intent", "unknown"),
            "action":     step.get("action", ""),
            "parameters": step.get("parameters", {}),
            "requires_confirmation": False,
        })
        results.append(f"Step {i}: {'OK' if sub['success'] else 'FAIL'} — {sub['output'] or sub['error']}")
        if not sub["success"]:
            break   # abort on first failure

    return _ok("\n".join(results))


# ── Reminders ─────────────────────────────────────────────────────────────────

_active_reminders: dict[str, threading.Timer] = {}


def _handle_reminder_task(action: str, params: dict) -> dict:
    if action == "set_reminder":
        msg   = params.get("message", "Reminder")
        delay = max(5, int(params.get("delay_seconds", 60)))   # floor = 5s

        def _fire():
            _active_reminders.pop(msg, None)
            # Import here to avoid circular at module load
            try:
                from core.signals import signals
                signals.status_changed.emit(f"REMINDER: {msg}")
            except Exception:
                pass
            if config.debug_mode:
                print(f"[reminder] {msg}")

        t = threading.Timer(delay, _fire)
        t.daemon = True
        t.start()
        _active_reminders[msg] = t
        mins = delay // 60
        secs = delay % 60
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        return _ok(f"Reminder set: '{msg}' in {time_str}")

    if action == "cancel_reminder":
        msg = params.get("message", "")
        t = _active_reminders.pop(msg, None)
        if t:
            t.cancel()
            return _ok(f"Reminder cancelled: {msg}")
        return _err(f"No active reminder: {msg}")

    if action == "list_reminders":
        if not _active_reminders:
            return _ok("No active reminders")
        return _ok("\n".join(_active_reminders.keys()))

    return _err(f"Unknown reminder action: {action}")


def _handle_jarvis_meta(action: str, params: dict) -> dict:
    from datetime import datetime
    if action == "tell_time":
        return _ok(datetime.now().strftime("%H:%M"))
    if action == "tell_date":
        return _ok(datetime.now().strftime("%A, %d %B %Y"))
    if action == "status_report":
        import psutil
        cpu  = psutil.cpu_percent(interval=0.3)
        mem  = psutil.virtual_memory()
        return _ok(f"CPU {cpu:.0f}%  MEM {mem.percent:.0f}%  ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)")
    return _ok(action)


def _handle_unknown(action: str, params: dict) -> dict:
    return _err("Intent not recognised")


# ── Dispatch table ────────────────────────────────────────────────────────────

_HANDLERS = {
    "open_app":           _handle_open_app,
    "close_app":          _handle_close_app,
    "search_web":         _handle_search_web,
    "type_text":          _handle_type_text,
    "control_mouse":      _handle_control_mouse,
    "system_control":     _handle_system_control,
    "file_operation":     _handle_file_operation,
    "code_execution":     _handle_code_execution,
    "browser_automation": _handle_browser_automation,
    "read_screen":        _handle_read_screen,
    "automation_task":    _handle_automation_task,
    "reminder_task":      _handle_reminder_task,
    "jarvis_meta":        _handle_jarvis_meta,
    "unknown":            _handle_unknown,
}


def dispatch(result: dict[str, Any]) -> dict[str, Any]:
    """Route a parsed intent dict to its OS handler.

    Never raises — wraps every handler in a try/except so the UI always
    receives a valid result dict.
    """
    intent = result.get("intent", "unknown")
    action = result.get("action", "")
    params = result.get("parameters", {})

    handler = _HANDLERS.get(intent, _handle_unknown)
    try:
        exec_result = handler(action, params)
    except Exception as exc:
        if config.debug_mode:
            print(f"[executor] Unhandled error in {intent}/{action}: {exc}")
        exec_result = _err(str(exc))

    return exec_result
