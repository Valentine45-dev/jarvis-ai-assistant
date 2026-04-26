"""
Command router — receives a parsed intent dict from brain.py and
dispatches it to the correct OS handler.

Each handler receives (action: str, params: dict) and returns
{"success": bool, "output": str, "error": str}.

Special key in return dict:
  "needs_confirmation": True — executor needs user yes/no before proceeding.
  Caller should speak output as the prompt, then call resolve_confirmation().
"""

from __future__ import annotations

import difflib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from config.settings import config
from core import computer_control as cc
from core.browser import browser

_OS = platform.system().lower()   # "windows" | "darwin" | "linux"


# ── Result helpers ────────────────────────────────────────────────────────────

def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}

def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


def _coerce_volume_level(params: dict) -> int | None:
    """Parse `parameters.level` for absolute 0–100% volume. Returns None to mean 'step up/down'."""
    raw = params.get("level")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    s = str(raw).strip().lower()
    if s in ("max", "full", "maximum", "100%", "all", "highest"):
        return 100
    if s.endswith("%"):
        try:
            return max(0, min(100, int(s[:-1].strip())))
        except ValueError:
            return None
    try:
        return max(0, min(100, int(float(s))))
    except ValueError:
        return None


def _confirm(prompt: str) -> dict:
    """Return a 'needs confirmation' sentinel with the prompt as output."""
    return {"success": True, "output": prompt, "error": "", "needs_confirmation": True}


# ── Page cache (shared with brain.py for context injection) ───────────────────

_PAGE_CACHE: dict[str, str] = {}


def get_page_cache() -> str | None:
    return _PAGE_CACHE.get("last_read")


def _set_page_cache(text: str) -> None:
    _PAGE_CACHE["last_read"] = text


# ── Confirmation loop ─────────────────────────────────────────────────────────

_PENDING: dict[str, Any] = {}   # {"fn": callable, "prompt": str}


def get_pending_confirmation() -> dict | None:
    return dict(_PENDING) if _PENDING else None


def request_confirmation(prompt: str, fn) -> dict:
    """Store a deferred action and return a confirmation-needed sentinel."""
    _PENDING.clear()
    _PENDING["fn"]     = fn
    _PENDING["prompt"] = prompt
    return _confirm(prompt)


def resolve_confirmation(user_response: str) -> dict:
    """Call with the user's yes/no reply. Executes or cancels the pending action."""
    if not _PENDING:
        return _err("No pending action to confirm.")
    _AFFIRMATIVE = {"yes", "yeah", "do it", "go ahead", "confirm", "sure", "ok",
                    "yep", "absolutely", "please", "create it", "proceed"}
    fn = _PENDING.pop("fn", None)
    _PENDING.clear()
    if any(w in user_response.strip().lower() for w in _AFFIRMATIVE):
        if fn:
            try:
                return fn()
            except Exception as exc:
                return _err(str(exc))
        return _err("Action missing.")
    return {"success": False, "output": "Understood, standing down, sir.", "error": ""}


# ── Path helpers ──────────────────────────────────────────────────────────────

def _safe_path(path_str: str) -> Path:
    """Resolve path, correcting wrong C:\\Users\\<bad_name> guesses."""
    if not path_str:
        return Path.home() / "jarvis_file.txt"

    p = Path(path_str).expanduser()
    home = Path.home()

    # Detect wrong username: path is under C:\Users\<X> but X != actual home name
    parts = p.parts
    if (len(parts) >= 3
            and parts[0].upper().rstrip("\\") in ("C:", "C:\\")
            and parts[1].lower() == "users"
            and parts[2].lower() != home.name.lower()
            and not (Path(parts[0]) / parts[1] / parts[2]).exists()):
        rest = parts[3:]
        p = home / Path(*rest) if rest else home

    return p


def _find_folder(name: str) -> Path | None:
    """Find a folder by name in common user locations (fuzzy, case-insensitive)."""
    home = Path.home()
    n = name.strip().lower()

    # Common shortcuts
    shortcuts: dict[str, Path] = {
        "downloads": home / "Downloads",
        "download":  home / "Downloads",
        "desktop":   home / "Desktop",
        "documents": home / "Documents",
        "document":  home / "Documents",
        "docs":      home / "Documents",
        "pictures":  home / "Pictures",
        "pics":      home / "Pictures",
        "photos":    home / "Pictures",
        "music":     home / "Music",
        "videos":    home / "Videos",
        "movies":    home / "Videos",
    }
    if n in shortcuts:
        p = shortcuts[n]
        return p if p.exists() else None

    # Exact match in first-level children of common roots
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home,
             Path("C:/Users"), home / "OneDrive"]
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.iterdir():
                if p.is_dir() and p.name.lower() == n:
                    return p
        except PermissionError:
            pass

    # Fuzzy search (one level deeper)
    candidates: list[tuple[float, Path]] = []
    for root in [home, home / "Desktop", home / "Documents", home / "Downloads"]:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if p.is_dir():
                    score = difflib.SequenceMatcher(None, p.name.lower(), n).ratio()
                    if score > 0.75:
                        candidates.append((score, p))
        except (PermissionError, OSError):
            pass

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return None


def _resolve_screenshot_path(save_param: str | None) -> tuple[str, str | None]:
    """
    Returns (resolved_save_path, folder_not_found_name | None).
    If second element is not None, caller should ask user to confirm folder creation.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"JARVIS_{ts}.png"

    if not save_param:
        return str(Path.home() / "Desktop" / fname), None

    p = Path(save_param).expanduser()

    # Full path with image extension → use directly
    if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return str(p), None

    # Existing directory → save inside it
    if p.is_dir():
        return str(p / fname), None

    # Single name (no separators) → treat as folder name to search for
    if len(p.parts) == 1:
        found = _find_folder(save_param)
        if found:
            return str(found / fname), None
        return "", save_param   # signal: folder not found

    # Absolute path to a dir that doesn't exist yet → create it
    if p.is_absolute():
        try:
            p.mkdir(parents=True, exist_ok=True)
            return str(p / fname), None
        except Exception:
            pass

    return str(Path.home() / "Desktop" / fname), None


# ── Windows app launcher ──────────────────────────────────────────────────────

_WIN_ALIASES: dict[str, str] = {
    "calculator": "calc",
    "calc":       "calc",
    "notepad":    "notepad",
    "paint":      "mspaint",
    "cmd":        "cmd",
    "command prompt": "cmd",
    "terminal":   "wt",
    "powershell": "powershell",
    "task manager": "taskmgr",
    "taskmgr":    "taskmgr",
    "file explorer": "explorer",
    "explorer":   "explorer",
    "chrome":     "chrome",
    "google chrome": "chrome",
    "firefox":    "firefox",
    "edge":       "msedge",
    "microsoft edge": "msedge",
    "spotify":    "Spotify",
    "discord":    "Discord",
    "steam":      "Steam",
    "vscode":     "Code",
    "vs code":    "Code",
    "visual studio code": "Code",
    "visual studio": "devenv",
    "zoom":       "Zoom",
    "slack":      "slack",
    "teams":      "Teams",
    "microsoft teams": "Teams",
    "obs":        "obs64",
    "vlc":        "vlc",
    "word":       "WINWORD",
    "excel":      "EXCEL",
    "powerpoint": "POWERPNT",
    "outlook":    "OUTLOOK",
    "onenote":    "ONENOTE",
    "snipping tool": "SnippingTool",
    "snip":       "SnippingTool",
    "whatsapp":   "WhatsApp",
    "telegram":   "Telegram",
    "cursor":     "cursor",
}


def _find_app_windows(name: str) -> str | None:
    """Search Windows for an app by name. Returns launch path or None."""
    n_lower = name.lower().strip()

    # 1. Built-in alias table
    alias = _WIN_ALIASES.get(n_lower)
    if alias:
        if shutil.which(alias):
            return alias
        # Try startfile-friendly name (works for UWP-launched shortcuts)
        return alias

    # 2. Direct PATH lookup (exact + .exe)
    for candidate in [name, name + ".exe", n_lower, n_lower + ".exe",
                      n_lower.replace(" ", "") + ".exe"]:
        if shutil.which(candidate):
            return candidate

    # 3. Windows Registry App Paths
    if _OS == "windows":
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(
                        hive,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                    )
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            stem = subkey_name.lower().replace(".exe", "").replace(" ", "")
                            ratio = difflib.SequenceMatcher(None, stem, n_lower.replace(" ", "")).ratio()
                            if ratio > 0.7 or n_lower.replace(" ", "") in stem:
                                subkey = winreg.OpenKey(key, subkey_name)
                                try:
                                    exe_path, _ = winreg.QueryValueEx(subkey, "")
                                    exe_path = exe_path.strip().strip('"')
                                    if exe_path and Path(exe_path).exists():
                                        return exe_path
                                except Exception:
                                    pass
                            i += 1
                        except OSError:
                            break
                except Exception:
                    pass
        except ImportError:
            pass

    # 4. Start Menu shortcut search
    start_dirs = []
    appdata = os.environ.get("APPDATA", "")
    prog_data = os.environ.get("PROGRAMDATA", "C:/ProgramData")
    if appdata:
        start_dirs.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    start_dirs.append(Path(prog_data) / "Microsoft/Windows/Start Menu/Programs")

    best_score = 0.0
    best_path  = None
    for base in start_dirs:
        if not base.exists():
            continue
        try:
            for lnk in base.rglob("*.lnk"):
                stem = lnk.stem.lower().replace(" ", "")
                ratio = difflib.SequenceMatcher(None, stem, n_lower.replace(" ", "")).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best_path  = str(lnk)
        except (PermissionError, OSError):
            pass

    if best_score > 0.65 and best_path:
        return best_path

    # 5. Search Program Files for .exe
    prog_dirs = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path.home() / "AppData/Local/Programs",
        Path.home() / "AppData/Local",
    ]
    n_words = set(n_lower.split())
    for base in prog_dirs:
        if not base.exists():
            continue
        try:
            for exe in base.rglob("*.exe"):
                stem = exe.stem.lower()
                if stem in n_lower or n_lower.replace(" ", "") in stem:
                    return str(exe)
                # Word overlap heuristic
                stem_words = set(stem.replace("-", " ").replace("_", " ").split())
                if n_words & stem_words and len(n_words & stem_words) / max(len(n_words), 1) > 0.5:
                    return str(exe)
        except (PermissionError, OSError):
            pass

    return None


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_open_app(action: str, params: dict) -> dict:
    app  = params.get("app_name", "")
    url  = params.get("url", "")

    if action == "open_url" or url:
        target = url or app
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        if not browser.is_ready:
            browser.start()
        if browser.is_ready:
            return browser.navigate(target)
        webbrowser.open(target)
        return _ok(f"Opened: {target}")

    if action == "open_browser":
        browser_name = params.get("browser", "chrome").lower()
        if not browser.is_ready:
            browser.start()
        if browser.is_ready:
            return _ok(f"Browser ready — {browser_name}")
        # Fallback
        browsers = {"chrome": "chrome", "firefox": "firefox", "edge": "msedge"}
        exe = browsers.get(browser_name, "chrome")
        if shutil.which(exe):
            subprocess.Popen([exe])
            return _ok(f"Opened {browser_name}")
        webbrowser.open("about:blank")
        return _ok("Opened default browser")

    # Generic app open
    name = app or action.replace("open_", "").replace("_", " ")
    if not name:
        return _err("No app name provided")

    if _OS == "windows":
        found = _find_app_windows(name)
        if found:
            try:
                os.startfile(found)
                return _ok(f"Launched {name}")
            except Exception as exc:
                # Try subprocess as fallback
                try:
                    subprocess.Popen([found], shell=False)
                    return _ok(f"Launched {name}")
                except Exception:
                    return _err(str(exc))
        # Last resort: try os.startfile with the raw name (handles UWP apps)
        try:
            os.startfile(name)
            return _ok(f"Launched {name}")
        except Exception:
            pass
        return _err(f"Application '{name}' not found on this device")

    # macOS / Linux
    if shutil.which(name):
        subprocess.Popen([name])
        return _ok(f"Launched {name}")
    if _OS == "darwin":
        result = subprocess.run(["open", "-a", name], capture_output=True, text=True)
        if result.returncode == 0:
            return _ok(f"Launched {name}")
    return _err(f"Application '{name}' not found")


def _handle_close_app(action: str, params: dict) -> dict:
    name = params.get("app_name", params.get("process_name", ""))
    if not name:
        return _err("No app name provided")
    if _OS == "windows":
        exe = name if name.endswith(".exe") else name + ".exe"
        flag = "/F" if action == "force_quit" else ""
        cmd = ["taskkill", "/F", "/IM", exe] if flag else ["taskkill", "/IM", exe]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return _ok(result.stdout.strip()) if result.returncode == 0 else _err(result.stderr.strip())
    flag = "-9" if action == "force_quit" else "-15"
    result = subprocess.run(["pkill", flag, name], capture_output=True, text=True)
    return _ok() if result.returncode == 0 else _err(f"Process not found: {name}")


def _handle_search_web(action: str, params: dict) -> dict:
    query        = params.get("query", "")
    platform_key = params.get("platform", "google")
    urls = {
        "google":        f"https://www.google.com/search?q={quote_plus(query)}",
        "youtube":       f"https://www.youtube.com/results?search_query={quote_plus(query)}",
        "github":        f"https://github.com/search?q={quote_plus(query)}",
        "stackoverflow": f"https://stackoverflow.com/search?q={quote_plus(query)}",
        "wikipedia":     f"https://en.wikipedia.org/wiki/Special:Search?search={quote_plus(query)}",
    }
    url = urls.get(platform_key, urls["google"])
    # Route through Playwright browser for consistent control
    if not browser.is_ready:
        browser.start()
    if browser.is_ready:
        return browser.navigate(url)
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
    if action in ("volume_up", "volume_down"):
        # Absolute level when e.g. "set to 100%" / "max" — any coerced 0–100
        return cc.set_volume(action, level=_coerce_volume_level(params))
    if action == "volume_mute":
        return cc.set_volume("volume_mute", level=None)

    if action == "screenshot":
        save_param = params.get("save_path") or params.get("folder") or None
        resolved, missing_folder = _resolve_screenshot_path(save_param)

        if missing_folder:
            # Ask user if they want to create the folder
            def _create_and_screenshot():
                folder = _find_folder(missing_folder)
                if not folder:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    folder = Path.home() / "Desktop"
                path = str(folder / f"JARVIS_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                return cc.screenshot(path=path)
            from core.personality import ask as _ask
            return request_confirmation(
                _ask("folder_not_found", missing_folder),
                _create_and_screenshot,
            )

        region = params.get("region")
        result = cc.screenshot(path=resolved, region=region)
        if result["success"]:
            # Trim path for display — show just the filename
            fname = Path(resolved).name
            result["output"] = fname
        return result

    if action == "lock_screen":
        return cc.lock_screen()

    if action in ("shutdown", "restart", "sleep"):
        cmds = {
            "windows": {
                "shutdown": ["shutdown", "/s", "/t", "5"],
                "restart":  ["shutdown", "/r", "/t", "5"],
                "sleep":    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            },
            "darwin": {
                "shutdown": ["sudo", "shutdown", "-h", "now"],
                "restart":  ["sudo", "shutdown", "-r", "now"],
                "sleep":    ["pmset", "sleepnow"],
            },
            "linux": {
                "shutdown": ["shutdown", "-h", "now"],
                "restart":  ["shutdown", "-r", "now"],
                "sleep":    ["systemctl", "suspend"],
            },
        }
        cmd = cmds.get(_OS, cmds["linux"]).get(action)
        if cmd:
            subprocess.Popen(cmd)
        return _ok(f"Executing: {action}")

    return _ok(f"System: {action}")


def _handle_file_operation(action: str, params: dict) -> dict:
    raw_path = params.get("path", "")
    path     = _safe_path(raw_path) if raw_path else Path.home() / "jarvis_file.txt"
    dest     = _safe_path(params["destination"]) if params.get("destination") else None

    if action == "create_file":
        content = params.get("content", "")

        # If path has no extension and no filename, add a default
        if not path.suffix and not raw_path.endswith("/") and not raw_path.endswith("\\"):
            path = path / "jarvis_note.txt"

        parent = path.parent

        if not parent.exists():
            folder_name = parent.name

            def _do_create():
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                    return _ok(f"Folder created and file saved: {path.name}")
                except PermissionError:
                    return _err(f"Permission denied creating folder: {parent}")
                except Exception as exc:
                    return _err(str(exc))

            from core.personality import ask as _ask
            return request_confirmation(
                _ask("folder_not_found", folder_name),
                _do_create,
            )

        try:
            path.write_text(content, encoding="utf-8")
            return _ok(f"Created: {path.name}")
        except PermissionError:
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            return _err(str(exc))

    if action == "read_file":
        if not path.exists():
            # Try to find the file by name in common locations
            found = _locate_file(path.name)
            if found:
                path = found
            else:
                return _err(f"File not found: {path.name}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return _ok(content[:2000])
        except PermissionError:
            return _err(f"Permission denied reading: {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "delete_file":
        if not path.exists():
            return _err(f"Not found: {path}")
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return _ok(f"Deleted: {path.name}")
        except PermissionError:
            return _err(f"Permission denied deleting: {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "move_file":
        if dest is None:
            return _err("No destination provided")
        try:
            shutil.move(str(path), str(dest))
            return _ok(f"Moved {path.name} to {dest.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "copy_file":
        if dest is None:
            return _err("No destination provided")
        try:
            shutil.copy2(str(path), str(dest))
            return _ok(f"Copied {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "list_directory":
        # If path doesn't exist, try to find by name
        if not path.exists():
            found_dir = _find_folder(raw_path) if raw_path else None
            if found_dir:
                path = found_dir
            else:
                return _err(f"Directory not found: {raw_path or path}")
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            lines = []
            for p in entries[:50]:
                icon = "📁" if p.is_dir() else "📄"
                lines.append(f"{icon} {p.name}")
            summary = f"{path.name}/ — {len(lines)} items:\n" + "\n".join(lines)
            return _ok(summary)
        except PermissionError:
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            return _err(str(exc))

    if action == "search_files":
        pattern = params.get("pattern", "*")
        base    = path if path.is_dir() else Path.home()
        try:
            results = [str(p) for p in base.rglob(pattern)][:30]
            if not results:
                return _ok("No matching files found.")
            return _ok("\n".join(Path(r).name for r in results))
        except Exception as exc:
            return _err(str(exc))

    return _err(f"Unknown file action: {action}")


def _locate_file(name: str) -> Path | None:
    """Search common locations for a file by name."""
    roots = [
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home(),
    ]
    for root in roots:
        try:
            for p in root.rglob(name):
                if p.is_file():
                    return p
        except (PermissionError, OSError):
            pass
    return None


def _handle_code_execution(action: str, params: dict) -> dict:
    code = params.get("code", params.get("script_path", ""))
    cwd  = params.get("working_directory", None)
    if not code:
        return _err("No code or command provided")

    if action == "run_python":
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        out = result.stdout or result.stderr
        return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])

    if action in ("run_shell", "git_command", "npm_command"):
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=60, cwd=cwd, shell=False,
            )
            out = (result.stdout or result.stderr or "").strip()
            return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])
        except subprocess.TimeoutExpired:
            return _err("Command timed out after 60s")
        except Exception as exc:
            return _err(str(exc))

    if action == "run_script":
        p = Path(code).expanduser()
        if not p.exists():
            return _err(f"Script not found: {p}")
        result = subprocess.run(
            [sys.executable, str(p)] if p.suffix == ".py" else [str(p)],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )
        return _ok(result.stdout[:2000]) if result.returncode == 0 else _err(result.stderr[:2000])

    return _err(f"Unknown code action: {action}")


def _handle_browser_automation(action: str, params: dict) -> dict:
    if not browser.is_ready:
        browser.start()
        if not browser.is_ready:
            return _err(browser._start_err or "Browser failed to start.")

    url = params.get("url", "")

    if action == "navigate":
        if not url:
            return _err("No URL provided")
        return browser.navigate(url)

    if action == "new_tab":
        return browser.new_tab(url)

    if action == "click_element":
        return browser.click_element(
            selector=params.get("selector", ""),
            text=params.get("text", ""),
            x=params.get("x"),
            y=params.get("y"),
        )

    if action == "fill_form":
        return browser.fill_form(params.get("fields", {}))

    if action in ("extract_text", "read_page"):
        selector = params.get("selector", "")
        result   = browser.extract_content(selector) if selector else browser.read_page()
        if result.get("success") and result.get("output"):
            _set_page_cache(result["output"])
        return result

    if action == "screenshot":
        selector = params.get("selector", "")
        path     = params.get("save_path") or None
        return (browser.screenshot_element(selector, path) if selector
                else browser.screenshot_page(path))

    if action == "close_tab":
        return browser.close_tab()

    return _err(f"Browser action not implemented: {action}")


def _handle_read_screen(action: str, params: dict) -> dict:
    region = params.get("region") if action == "ocr_region" else None
    result = cc.ocr_screen(region=region)
    if result.get("success") and result.get("output"):
        _set_page_cache(result["output"])
    return result


# ── Automation ────────────────────────────────────────────────────────────────

_DANGEROUS_STEPS: frozenset[tuple[str, str]] = frozenset({
    ("file_operation",  "delete_file"),
    ("system_control",  "shutdown"),
    ("system_control",  "restart"),
    ("system_control",  "sleep"),
    ("close_app",       "force_quit"),
})

_BLOCKED_INTENTS: frozenset[str] = frozenset({"code_execution"})

_CONFIRMATION_REQUIRED_ACTIONS: frozenset[tuple[str, str]] = frozenset({
    ("automation_task", "remove_workflow"),
    ("file_operation",  "delete_file"),
    ("system_control",  "shutdown"),
    ("system_control",  "restart"),
    ("system_control",  "sleep"),
    ("close_app",       "force_quit"),
})

_KNOWN_STEP_INTENTS: frozenset[str] = frozenset({
    "open_app", "close_app", "search_web", "type_text", "control_mouse",
    "system_control", "file_operation", "browser_automation",
    "read_screen", "reminder_task", "jarvis_meta",
})


def _handle_automation_task(action: str, params: dict) -> dict:
    from core.automation import workflow_library

    if action == "list_workflows":
        workflows = workflow_library.list_all()
        if not workflows:
            return _ok("No workflows defined.")
        lines = [
            f"- {w['name']}  [{w['id']}]  {'ON' if w.get('enabled') else 'OFF'}"
            for w in workflows
        ]
        return _ok("\n".join(lines))

    if action == "create_workflow":
        task_name = params.get("task_name", "")
        steps     = params.get("steps", [])
        if not task_name:
            return _err("No task_name provided for workflow creation.")
        if not isinstance(steps, list) or not steps:
            return _err("Steps must be a non-empty list.")
        slug = task_name.lower().replace(" ", "_")
        if workflow_library.get(slug) is not None:
            return _err(f"Workflow '{task_name}' already exists.")
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                return _err(f"Step {i} must be a dict.")
            s_intent = step.get("intent", "")
            s_action = step.get("action", "")
            if not s_intent:
                return _err(f"Step {i} is missing 'intent'.")
            if s_intent in _BLOCKED_INTENTS:
                return _err(f"Step {i} uses blocked intent '{s_intent}'.")
            if s_intent not in _KNOWN_STEP_INTENTS:
                return _err(f"Step {i} has unrecognised intent '{s_intent}'.")
            if (s_intent, s_action) in _DANGEROUS_STEPS:
                return _err(f"Step {i} contains dangerous action '{s_action}'.")
        wf = {
            "id": slug, "name": task_name, "trigger": "Manual",
            "enabled": True, "last_run": "", "steps": steps,
        }
        workflow_library.add(wf)
        return _ok(f"Workflow '{task_name}' created with {len(steps)} step(s).")

    if action == "remove_workflow":
        task_name = params.get("task_name", "")
        if not task_name:
            return _err("No task_name provided.")
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow '{task_name}' not found.")
        workflow_library.remove(wf["id"])
        return _ok(f"Workflow '{wf['name']}' deleted.")

    if action == "rename_workflow":
        task_name = params.get("task_name", "")
        new_name  = params.get("new_name", "")
        if not task_name or not new_name:
            return _err("Both task_name and new_name are required.")
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow '{task_name}' not found.")
        new_slug = new_name.lower().replace(" ", "_")
        if new_slug != wf["id"] and workflow_library.get(new_slug) is not None:
            return _err(f"A workflow named '{new_name}' already exists.")
        workflow_library.rename(wf["id"], new_name)
        return _ok(f"Workflow renamed to '{new_name}'.")

    # run_workflow
    steps     = params.get("steps", [])
    task_name = params.get("task_name", "")
    workflow_id: str = ""

    if task_name and not steps:
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow not found: {task_name!r}")
        if not wf.get("enabled", True):
            return _err(f"Workflow '{wf['name']}' is disabled.")
        steps       = wf.get("steps", [])
        workflow_id = wf.get("id", "")

    if not steps:
        return _err("No steps provided in automation task")

    for step in steps:
        intent = step.get("intent", "")
        s_action = step.get("action", "")
        if intent in _BLOCKED_INTENTS:
            return _err(f"Workflow contains a '{intent}' step requiring manual confirmation.")
        if (intent, s_action) in _DANGEROUS_STEPS:
            return _err(f"Workflow contains dangerous step '{s_action}' — run manually.")

    total   = len(steps)
    results = []
    all_ok  = True
    for i, step in enumerate(steps, 1):
        try:
            from core.signals import signals
            signals.status_changed.emit(
                f"Automation: step {i}/{total} — {step.get('action', '').replace('_', ' ')}"
            )
        except Exception:
            pass
        sub = dispatch({
            "intent":     step.get("intent", "unknown"),
            "action":     step.get("action", ""),
            "parameters": step.get("parameters", {}),
            "requires_confirmation": False,
        })
        results.append(f"Step {i}: {'OK' if sub['success'] else 'FAIL'} — {sub['output'] or sub['error']}")
        if not sub["success"]:
            all_ok = False
            break

    if workflow_id and all_ok:
        workflow_library.mark_run(workflow_id)

    summary = "\n".join(results)
    return _ok(summary) if all_ok else _err(summary)


# ── Reminders ─────────────────────────────────────────────────────────────────

_active_reminders: dict[str, threading.Timer] = {}


def _handle_reminder_task(action: str, params: dict) -> dict:
    if action == "set_reminder":
        msg   = params.get("message", "Reminder")
        delay = max(5, int(params.get("delay_seconds", 60)))

        def _fire():
            _active_reminders.pop(msg, None)
            try:
                from core.signals import signals
                signals.status_changed.emit(f"REMINDER: {msg}")
            except Exception:
                pass

        t = threading.Timer(delay, _fire)
        t.daemon = True
        t.start()
        _active_reminders[msg] = t
        mins = delay // 60
        secs = delay % 60
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        return _ok(f"In {time_str}: {msg}")

    if action == "cancel_reminder":
        msg = params.get("message", "")
        t   = _active_reminders.pop(msg, None)
        if t:
            t.cancel()
            return _ok(f"Reminder cancelled: {msg}")
        return _err(f"No active reminder matching: {msg}")

    if action == "list_reminders":
        if not _active_reminders:
            return _ok("No active reminders.")
        return _ok(", ".join(_active_reminders.keys()))

    return _err(f"Unknown reminder action: {action}")


# ── Jarvis meta ───────────────────────────────────────────────────────────────

def _handle_jarvis_meta(action: str, params: dict) -> dict:
    if action == "tell_time":
        # Return raw time — personality.say() formats the sentence
        return _ok(datetime.now().strftime("%I:%M %p").lstrip("0"))
    if action == "tell_date":
        # Return raw date — personality.say() formats the sentence
        return _ok(datetime.now().strftime("%A, %d %B %Y"))
    if action == "status_report":
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        return _ok(
            f"CPU {cpu:.0f}%, memory {mem.percent:.0f}% "
            f"({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)"
        )
    if action == "conversational":
        # Check page cache for "what does it say" queries
        cached = get_page_cache()
        if cached:
            return _ok(cached[:800])
        return _ok("")
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


def dispatch(result: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
    """Route a parsed intent dict to its OS handler.

    confirmed=True must be passed for destructive actions.
    Never raises — wraps every handler in try/except.
    """
    intent = result.get("intent", "unknown")
    action = result.get("action", "")
    params = result.get("parameters", {})

    needs_confirmation = (
        result.get("requires_confirmation")
        or (intent, action) in _CONFIRMATION_REQUIRED_ACTIONS
    )
    if needs_confirmation and not confirmed:
        return _err(f"Action '{action}' requires confirmation before execution.")

    handler = _HANDLERS.get(intent, _handle_unknown)
    try:
        return handler(action, params)
    except Exception as exc:
        if config.debug_mode:
            print(f"[executor] Unhandled error in {intent}/{action}: {exc}")
        return _err(str(exc))
