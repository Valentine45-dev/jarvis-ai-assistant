"""Handlers: open_app, close_app, search_web — plus Windows app resolution."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from core.handlers.shared import _OS, _ok, _err, _clear_page_cache, _set_page_cache, _tlog

# Bounds for Program Files / AppData exe scanning — keep cold lookups snappy.
_APP_SCAN_TIME_BUDGET_S = 5.0
_APP_SCAN_CANDIDATE_CAP = 50
_APP_SCAN_PRUNE_DIRS: frozenset[str] = frozenset({
    "node_modules", "__pycache__", ".git", ".venv", "common files",
    "windows kits", "microsoft",  # AppData/Local/Microsoft and shared SDKs
})


# ── Windows alias table ───────────────────────────────────────────────────────

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

# Spoken browser name → controlled-engine key for open_browser. Anything not
# here falls back to chrome. "auto" lets the session pick the first installed.
_BROWSER_NAME_TO_ENGINE: dict[str, str] = {
    "chrome": "chrome", "google chrome": "chrome", "google": "chrome",
    "edge": "edge", "microsoft edge": "edge", "msedge": "edge",
    "firefox": "firefox", "mozilla": "firefox", "mozilla firefox": "firefox",
    "auto": "auto", "default": "auto",
}

_WIN_APPID_PREFIX = "__WIN_APPID__:"
_WIN_PROTO_PREFIX = "__WIN_PROTO__:"

_proto_cache: list[str] | None = None
_proto_cache_m: float = 0.0
_PROTO_CACHE_TTL_S = 120.0


def _win_subprocess_flags() -> int:
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def _norm_query_compact(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower().strip())


def _exe_stem_matches_query(user_query: str, stem: str) -> bool:
    n_q = _norm_query_compact(user_query)
    stem = (stem or "").lower().replace(" ", "").replace(".exe", "")
    if not stem or not n_q:
        return False
    if n_q == stem:
        return True
    try:
        return re.search(
            r"(?<![a-z0-9])" + re.escape(stem) + r"(?![a-z0-9])",
            n_q,
            re.IGNORECASE,
        ) is not None
    except re.error:
        return False


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _query_display_score(n_user: str, display: str) -> float:
    nq = _norm_query_compact(n_user)
    dc = _norm_query_compact(display)
    if not nq or not dc:
        return 0.0
    r0 = _name_similarity(nq, dc)
    tq = set(re.findall(r"[a-z0-9]{2,}", n_user.lower()))
    td = set(re.findall(r"[a-z0-9]{2,}", display.lower()))
    if not tq or not td:
        return r0
    inter = tq & td
    un = tq | td
    j = (len(inter) / len(un)) if un else 0.0
    return min(1.0, 0.52 * r0 + 0.48 * j + (0.12 if tq.issubset(td) or td.issubset(tq) else 0.0))


def _score_query_vs_url_protocol(n_user: str, proto: str) -> float:
    nq = _norm_query_compact(n_user)
    pl = (proto or "").lower().strip()
    if not nq or not pl:
        return 0.0
    p_body = re.sub(r"^ms-|^ms\.|^com\.", "", pl)
    p_body = p_body.replace(".", "").replace("-", "")
    p_body_spaced = re.sub(
        r"^ms-|^ms\.", "", (proto or "").lower()
    ).replace(".", " ").replace("-", " ")
    r0 = max(
        _name_similarity(nq, p_body),
        _name_similarity(nq, _norm_query_compact(p_body_spaced)),
    )
    tq = set(re.findall(r"[a-z0-9]{2,}", n_user.lower()))
    p_tokens = re.findall(
        r"[a-z0-9]{2,}", pl.replace(".", " ").replace("-", " ").replace("_", " ")
    )
    ps = set(p_tokens)
    if not tq or not ps:
        base = 0.55 * r0
    else:
        j = len(tq & ps) / len(tq | ps) if (tq | ps) else 0.0
        j = max(j, _query_display_score(n_user, p_body_spaced))
        base = min(1.0, 0.45 * r0 + 0.55 * j)
    pl_flat = re.sub(r"[^a-z0-9]+", "", pl)
    for t in tq:
        if len(t) >= 3 and t in pl_flat:
            base = min(1.0, base + 0.2)
    return min(1.0, base)


def _registry_key_matches(n_compact: str, reg_stem: str, n_user: str) -> bool:
    r = _name_similarity(n_compact, reg_stem)
    if r >= 0.91:
        return True
    if r >= 0.84 and _exe_stem_matches_query(n_user, reg_stem):
        return True
    if r >= 0.80 and _exe_stem_matches_query(n_user, reg_stem):
        return True
    return r >= 0.93


def _get_windows_startapps() -> list[tuple[str, str]]:
    if _OS != "windows":
        return []
    try:
        ps = (
            "if (Get-Command Get-StartApps -ErrorAction SilentlyContinue) { "
            "Get-StartApps | ForEach-Object { [PSCustomObject]@{N=$_.Name;I=$_.AppId} } | ConvertTo-Json -Compress } "
            "else { '[]' }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=25,
            creationflags=_win_subprocess_flags(),
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            return []
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        out: list[tuple[str, str]] = []
        for row in data or []:
            if not isinstance(row, dict):
                continue
            n = (row.get("N") or row.get("Name") or "").strip()
            i = (row.get("I") or row.get("AppId") or "").strip()
            if n and i:
                out.append((n, i))
        return out
    except Exception:
        return []


def _get_shell_appsfolder_apps() -> list[tuple[str, str]]:
    if _OS != "windows":
        return []
    try:
        ps = r"""
$a = [System.Collections.Generic.List[object]]::new()
try {
  $sh = New-Object -ComObject Shell.Application
  $f = $sh.NameSpace('shell:AppsFolder')
  if ($null -ne $f) { foreach ($it in $f.Items()) {
    if ($it.Name -and $it.Path) { $a.Add([PSCustomObject]@{N=$it.Name;I=$it.Path}) }
  } }
} catch { }
@($a) | ConvertTo-Json -Compress
"""
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-Command", ps],
            capture_output=True, text=True, timeout=60,
            creationflags=_win_subprocess_flags(),
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            return []
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        out: list[tuple[str, str]] = []
        for row in data or []:
            if not isinstance(row, dict):
                continue
            n = (row.get("N") or row.get("Name") or "").strip()
            i = (row.get("I") or row.get("Path") or "").strip()
            if n and i:
                out.append((n, i))
        return out
    except Exception:
        return []


def _merge_startapp_rows(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    by_id: dict[str, str] = {}
    for name, app_id in pairs:
        k = (app_id or "").strip()
        if not k:
            continue
        nm = (name or "").strip()
        if k not in by_id or len(nm) > len(by_id[k]):
            by_id[k] = nm
    return [(v, k) for k, v in by_id.items()]


def _get_all_startapp_rows() -> list[tuple[str, str]]:
    a = _get_windows_startapps()
    b = _get_shell_appsfolder_apps()
    return _merge_startapp_rows(a + b)


def _get_ms_url_protocols_cached() -> list[str]:
    global _proto_cache, _proto_cache_m
    now = time.monotonic()
    if _proto_cache is not None and (now - _proto_cache_m) < _PROTO_CACHE_TTL_S:
        return _proto_cache
    _proto_cache_m = now
    _proto_cache = []
    if _OS != "windows":
        return _proto_cache
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as h_root:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(h_root, idx)
                except OSError:
                    break
                idx += 1
                if not name.startswith("ms-"):
                    continue
                try:
                    with winreg.OpenKey(h_root, name) as k:
                        winreg.QueryValueEx(k, "URL Protocol")
                    _proto_cache.append(name)
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return _proto_cache or []


def _best_url_protocol(n_user: str) -> str | None:
    protos = _get_ms_url_protocols_cached()
    if not protos:
        return None
    best: str | None = None
    best_s = 0.0
    for p in protos:
        s = _score_query_vs_url_protocol(n_user, p)
        if s > best_s:
            best_s = s
            best = p
    if best is None or best_s < 0.36:
        return None
    return best


def _best_startapp_id(n_user: str, rows: list[tuple[str, str]]) -> tuple[str, str] | None:
    if not (n_user or "").strip() or not rows:
        return None
    best: tuple[str, str] | None = None
    best_s = 0.0
    for display, app_id in rows:
        s = _query_display_score(n_user, display)
        toks = re.findall(r"[a-z0-9]{3,}", display.lower())
        tok_ok = any(_exe_stem_matches_query(n_user, t) for t in toks)
        if s < 0.52 and not (tok_ok and s >= 0.44):
            continue
        if s < 0.42:
            continue
        if s > best_s:
            best_s = s
            best = (display, app_id)
    if best is None or best_s < 0.50:
        return None
    return best


def _find_app_windows(name: str) -> str | None:
    n_user   = (name or "").strip()
    n_lower  = n_user.lower()
    n_compact = _norm_query_compact(n_user)

    alias = _WIN_ALIASES.get(n_lower)
    if alias:
        return alias

    start_rows = _get_all_startapp_rows()
    picked = _best_startapp_id(n_user, start_rows)
    if picked is not None:
        _disp, app_id = picked
        return f"{_WIN_APPID_PREFIX}{app_id}"

    start_dirs: list[Path] = []
    appdata   = os.environ.get("APPDATA", "")
    prog_data = os.environ.get("PROGRAMDATA", "C:/ProgramData")
    if appdata:
        start_dirs.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    start_dirs.append(Path(prog_data) / "Microsoft/Windows/Start Menu/Programs")

    best_lnk: str | None = None
    best_r_lnk = 0.0
    for base in start_dirs:
        if not base.exists():
            continue
        try:
            for lnk in base.rglob("*.lnk"):
                stem = lnk.stem.lower().replace(" ", "")
                r = _query_display_score(n_user, lnk.stem)
                if r < 0.68:
                    continue
                if not ((r >= 0.9) or (r >= 0.72 and _exe_stem_matches_query(n_user, stem))):
                    continue
                if r > best_r_lnk:
                    best_r_lnk = r
                    best_lnk = str(lnk)
        except (PermissionError, OSError):
            pass
    if best_lnk and best_r_lnk >= 0.72:
        return best_lnk

    for candidate in [name, name + ".exe", n_lower, n_lower + ".exe", n_compact + ".exe"]:
        w = shutil.which(candidate)
        if w:
            return w

    if _OS == "windows":
        try:
            import winreg
            reg_best: str | None = None
            reg_r = 0.0
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
                        except OSError:
                            break
                        i += 1
                        stem = subkey_name.lower().replace(".exe", "").replace(" ", "")
                        if not _registry_key_matches(n_compact, stem, n_user):
                            continue
                        r = _name_similarity(n_compact, stem)
                        if r < 0.78 and not _exe_stem_matches_query(n_user, stem):
                            continue
                        try:
                            subk = winreg.OpenKey(key, subkey_name)
                            try:
                                exe_path, _ = winreg.QueryValueEx(subk, "")
                            finally:
                                winreg.CloseKey(subk)
                            exe_path = exe_path.strip().strip('"')
                            if exe_path and Path(exe_path).exists() and r > reg_r:
                                reg_r = r
                                reg_best = exe_path
                        except OSError:
                            pass
                except OSError:
                    pass
            if reg_best and reg_r >= 0.78:
                return reg_best
        except ImportError:
            pass

    prog_dirs = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path.home() / "AppData/Local/Programs",
        Path.home() / "AppData/Local",
    ]
    best_exe: str | None = None
    best_r_exe = 0.0
    candidates_seen = 0
    deadline = time.monotonic() + _APP_SCAN_TIME_BUDGET_S
    timed_out = False
    for base in prog_dirs:
        if timed_out:
            break
        if not base.exists():
            continue
        try:
            for dirpath, dirs, files in os.walk(str(base)):
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                dirs[:] = [d for d in dirs if d.lower() not in _APP_SCAN_PRUNE_DIRS]
                for fname in files:
                    if not fname.lower().endswith(".exe"):
                        continue
                    stem = fname[:-4].lower()
                    r = _name_similarity(n_compact, stem.replace(" ", ""))
                    if (r >= 0.90) or (r >= 0.84 and _exe_stem_matches_query(n_user, stem)):
                        if r > best_r_exe:
                            best_r_exe = r
                            best_exe = str(Path(dirpath) / fname)
                        candidates_seen += 1
                        if candidates_seen >= _APP_SCAN_CANDIDATE_CAP:
                            timed_out = True
                            break
                if timed_out:
                    break
        except (PermissionError, OSError):
            pass
    if best_exe and best_r_exe >= 0.8:
        return best_exe

    proto = _best_url_protocol(n_user)
    if proto:
        return _WIN_PROTO_PREFIX + proto

    return None


# ── Native-app shortcuts (calc, notepad — cross-platform) ────────────────────

# Per-platform command chains. First entry that launches wins; later entries
# are fallbacks for distros that don't ship the default.
_NATIVE_APP_CMDS: dict[str, dict[str, list[list[str]]]] = {
    "calculator": {
        "windows": [["calc"]],
        "darwin":  [["open", "-a", "Calculator"]],
        "linux":   [["gnome-calculator"], ["kcalc"], ["xcalc"]],
    },
    "notepad": {
        "windows": [["notepad"]],
        "darwin":  [["open", "-a", "TextEdit"]],
        "linux":   [["gedit"], ["kate"], ["gnome-text-editor"], ["nano"]],
    },
}


def _launch_native_app(app_key: str) -> dict:
    """Try a chain of platform-specific commands until one launches.

    Used by ``open_calculator`` / ``open_notepad`` so the canonical native apps
    are reachable without depending on the Windows alias map or fuzzy Start
    Menu search.
    """
    chains = _NATIVE_APP_CMDS.get(app_key, {}).get(_OS, [])
    last_err = ""
    for cmd in chains:
        if not cmd:
            continue
        exe = cmd[0]
        # On non-Windows, gate by shutil.which so we skip missing binaries fast.
        # On Windows, `calc` / `notepad` are system shims not always on the
        # which-path; let Popen handle the FileNotFoundError.
        if _OS != "windows" and not shutil.which(exe):
            continue
        try:
            subprocess.Popen(cmd, creationflags=_win_subprocess_flags())
            return _ok(f"Launched {app_key}")
        except FileNotFoundError as exc:
            last_err = str(exc)
            continue
        except Exception as exc:
            return _err(str(exc))
    return _err(last_err or f"No {app_key} app available on {_OS}.")


# ── Intent handlers ───────────────────────────────────────────────────────────

def _handle_open_app(action: str, params: dict) -> dict:
    result = _handle_open_app_inner(action, params)
    if result.get("success"):
        _tlog("✓ launched")
    else:
        _tlog(f"✗ {result.get('error') or 'launch failed'}")
    return result


def _handle_open_app_inner(action: str, params: dict) -> dict:
    from core.browser import browser

    app = params.get("app_name", "")
    url = params.get("url", "")

    if action == "open_url" or url:
        target = url or app
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        _tlog(f"❯ launch {target}")
        if not browser.is_ready:
            browser.start()
        if browser.is_ready:
            return browser.navigate(target)
        webbrowser.open(target)
        return _ok(f"Opened: {target}")

    if action == "open_browser":
        raw = (params.get("browser") or "").lower().strip()
        if raw:
            # An engine was named ("open firefox") — honour it.
            browser_name = raw
        else:
            # No engine named ("open browser") — open the CONFIGURED default
            # (config.browser_engine), not a hardcoded 'chrome'. This is the bug:
            # the old `or "chrome"` default ignored the user's Default Browser
            # setting entirely. ('auto' resolves to first-installed downstream.)
            from config.settings import config as _cfg
            browser_name = (getattr(_cfg, "browser_engine", "") or "chrome").lower().strip()
        engine = _BROWSER_NAME_TO_ENGINE.get(browser_name, "chrome")
        _tlog(f"❯ {engine} browser")
        # Drive the controlled engine: launches if cold, switches if already
        # alive (instant pointer flip — closes nothing), no-op if already active.
        result = browser.ensure_engine(engine)
        if result.get("success"):
            _tlog(f"✓ {result.get('output') or engine}")
            return result
        # Controlled launch failed (e.g. profile in use). If the real app exists,
        # fall back to an uncontrolled launch so the user still gets the browser;
        # otherwise surface the clean reason (e.g. "Edge isn't installed").
        exe = {"chrome": "chrome", "edge": "msedge", "firefox": "firefox"}.get(engine, "chrome")
        if shutil.which(exe):
            subprocess.Popen([exe])
            _tlog(f"✓ opened {browser_name} (uncontrolled)")
            return _ok(f"Opened {browser_name}")
        _tlog(f"✗ {result.get('error') or 'browser unavailable'}")
        return result

    if action in ("open_calculator", "open_notepad"):
        app_key = action.replace("open_", "")
        _tlog(f"❯ launch {app_key}")
        return _launch_native_app(app_key)

    name = app or action.replace("open_", "").replace("_", " ")
    if not name:
        _tlog("❯ launch (no app name)")
        return _err("No app name provided")

    _tlog(f"❯ launch {name}")

    if _OS == "windows":
        found = _find_app_windows(name)
        if found:
            if found.startswith(_WIN_APPID_PREFIX):
                app_uri = "shell:AppsFolder\\" + found[len(_WIN_APPID_PREFIX):]
                try:
                    os.startfile(app_uri)
                    return _ok(f"Launched {name}")
                except Exception:
                    try:
                        subprocess.Popen(
                            ["explorer", app_uri],
                            shell=False,
                            creationflags=_win_subprocess_flags(),
                        )
                        return _ok(f"Launched {name}")
                    except Exception as exc:
                        pkey = _best_url_protocol(name)
                        if pkey:
                            p_uri = f"{pkey}:"
                            try:
                                os.startfile(p_uri)
                                return _ok(f"Launched {name}")
                            except Exception:
                                try:
                                    subprocess.run(
                                        ["cmd", "/c", "start", "", p_uri],
                                        shell=False,
                                        creationflags=_win_subprocess_flags(),
                                        check=False,
                                    )
                                    return _ok(f"Launched {name}")
                                except Exception:
                                    return _err(str(exc))
                        return _err(str(exc))
            if found.startswith(_WIN_PROTO_PREFIX):
                pkey = found[len(_WIN_PROTO_PREFIX):]
                p_uri = f"{pkey}:"
                try:
                    os.startfile(p_uri)
                    return _ok(f"Launched {name}")
                except Exception:
                    try:
                        subprocess.run(
                            ["cmd", "/c", "start", "", p_uri],
                            shell=False,
                            creationflags=_win_subprocess_flags(),
                            check=False,
                        )
                        return _ok(f"Launched {name}")
                    except Exception as exc2:
                        return _err(str(exc2))
            try:
                os.startfile(found)
                return _ok(f"Launched {name}")
            except Exception as exc:
                try:
                    subprocess.Popen([found], shell=False)
                    return _ok(f"Launched {name}")
                except Exception:
                    return _err(str(exc))
        try:
            os.startfile(name)
            return _ok(f"Launched {name}")
        except Exception:
            pass
        return _err(f"Application '{name}' not found on this device")

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
    is_force = action == "force_quit"
    if not name:
        _tlog(f"❯ {'force quit' if is_force else 'close'} (no name)")
        _tlog("✗ no app name provided")
        return _err("No app name provided")
    _tlog(f"❯ {'force quit' if is_force else 'close'} {name}")
    if _OS == "windows":
        exe = name if name.endswith(".exe") else name + ".exe"
        # Always use /F on Windows — graceful close often fails for multi-process
        # apps like Chrome; /F is safe and reliable for desktop app termination.
        result = subprocess.run(
            ["taskkill", "/F", "/IM", exe], capture_output=True, text=True
        )
        if result.returncode == 0:
            _tlog("✓ terminated" if is_force else "✓ closed")
            return _ok(result.stdout.strip())
        err_msg = result.stderr.strip()
        _tlog(f"✗ {err_msg or 'close failed'}")
        return _err(err_msg)
    flag = "-9" if is_force else "-15"
    result = subprocess.run(["pkill", flag, name], capture_output=True, text=True)
    if result.returncode == 0:
        _tlog("✓ terminated" if is_force else "✓ closed")
        return _ok()
    _tlog(f"✗ process not found: {name}")
    return _err(f"Process not found: {name}")


def _handle_search_web(action: str, params: dict) -> dict:
    query        = params.get("query", "")
    platform_key = params.get("platform", "google")
    _tlog(f"❯ search {query!r} on {platform_key}")

    # Opt-in explicit-content gate (default OFF): confirm before an adult query
    # so a shared/family machine doesn't surface NSFW results on a careless or
    # misheard command. A speed-bump, never a refusal — JARVIS stays a controller.
    from config.settings import config
    if getattr(config, "safe_search_confirm", False):
        from core.content_gate import is_explicit_query
        if is_explicit_query(query):
            from core.handlers.shared import request_confirmation
            _tlog("⚠ explicit query — awaiting confirmation (safe_search_confirm on)")
            prompt = (
                f'That search looks explicit — "{query}". '
                f"Search {platform_key} anyway?"
            )
            return request_confirmation(
                prompt, lambda: _do_search_web(query, platform_key)
            )
    return _do_search_web(query, platform_key)


def _do_search_web(query: str, platform_key: str) -> dict:
    from core.browser import browser

    urls = {
        "google":        f"https://www.google.com/search?q={quote_plus(query)}",
        "youtube":       f"https://www.youtube.com/results?search_query={quote_plus(query)}",
        "github":        f"https://github.com/search?q={quote_plus(query)}",
        "stackoverflow": f"https://stackoverflow.com/search?q={quote_plus(query)}",
        "wikipedia":     f"https://en.wikipedia.org/wiki/Special:Search?search={quote_plus(query)}",
    }
    url = urls.get(platform_key, urls["google"])
    # P3 BUG B: a new search is a topic change — drop any stale page cache so a
    # prior page can't ground THIS search's follow-ups (or a later unrelated
    # question). Cleared for ALL platforms; google then re-populates it below
    # via read_page, navigational platforms (youtube/github/…) leave it empty.
    _clear_page_cache()
    if not browser.is_ready:
        browser.start()
    if browser.is_ready:
        result = browser.navigate(url)
        if result.get("success"):
            _tlog("✓ opened")
            # P3 (fake-success #2): ground follow-ups in the ACTUAL results. Search
            # used to only navigate, so a follow-up ("summarize", "yes briefly") had
            # no page content in the cache → the brain answered current/dated facts
            # from training (e.g. the 2025 MVP for a 2026 question), confidently and
            # unsourced. Read the Google SERP into the page cache — the SAME channel
            # read_page uses (brain injects it as <page_content>) — so the next turn
            # is grounded. Google only: youtube/github/etc. are navigational, not
            # fact-answering. Best-effort: a read failure never fails the search.
            if platform_key == "google":
                try:
                    page = browser.read_page()
                    if page.get("success") and page.get("output"):
                        _set_page_cache(page["output"])
                        _tlog("↳ results cached for follow-up")
                except Exception:
                    pass
        else:
            _tlog(f"✗ {result.get('error') or 'navigation failed'}")
        return result
    try:
        webbrowser.open(url)
        _tlog("✓ opened")
        return _ok(f"Searching {platform_key} for: {query}")
    except Exception as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))
