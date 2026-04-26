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
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
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
    """Return a 'needs confirmation' sentinel with the prompt as output.

    success is False so nested dispatch (e.g. automation steps) does not count
    this step as completed until the user confirms; main still handles UI via
    needs_confirmation before checking success.
    """
    return {"success": False, "output": prompt, "error": "", "needs_confirmation": True}


# ── Page cache (shared with brain.py for context injection) ───────────────────

_PAGE_CACHE: dict[str, str] = {}


def get_page_cache() -> str | None:
    return _PAGE_CACHE.get("last_read")


def _set_page_cache(text: str) -> None:
    _PAGE_CACHE["last_read"] = text


# ── Confirmation loop ─────────────────────────────────────────────────────────

class _PendingConfirmation:
    """Typed container for a single in-flight confirmation request.

    Only one can exist at a time. `confirm_id` lets callers detect stale
    resolves (e.g. a reminder fires mid-confirm and changes state).
    """
    __slots__ = ("confirm_id", "fn", "prompt")

    def __init__(self, confirm_id: str, fn, prompt: str) -> None:
        self.confirm_id = confirm_id
        self.fn         = fn
        self.prompt     = prompt


_pending_confirmation: _PendingConfirmation | None = None


def get_pending_confirmation() -> dict | None:
    if _pending_confirmation is None:
        return None
    return {"fn": _pending_confirmation.fn, "prompt": _pending_confirmation.prompt,
            "confirm_id": _pending_confirmation.confirm_id}


def abandon_pending_confirmation() -> None:
    """Drop a deferred action without running it (e.g. user sent a new full command)."""
    global _pending_confirmation
    _pending_confirmation = None


def request_confirmation(prompt: str, fn) -> dict:
    """Store a deferred action and return a confirmation-needed sentinel.

    Replaces any previous pending action — only one can be in flight at a time.
    The returned sentinel carries the `confirm_id` so callers can detect stale resolves.
    """
    global _pending_confirmation
    cid = str(uuid.uuid4())
    _pending_confirmation = _PendingConfirmation(cid, fn, prompt)
    return _confirm(prompt)


def _is_affirmative_reply(user_response: str) -> bool:
    """True if the user is confirming (word-safe; avoids substring false positives)."""
    import re
    t = user_response.strip().lower()
    if not t:
        return False
    for phrase in (
        "go ahead", "do it", "create it", "sounds good", "that's fine",
        "as planned", "please do", "proceed", "yes please",
    ):
        if phrase in t:
            return True
    if t in ("y", "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "please", "k"):
        return True
    toks = set(re.findall(r"[a-z0-9']+", t))
    if toks & {"yes", "yeah", "yep", "sure", "confirm", "proceed", "absolutely", "ok"}:
        return True
    return False


def resolve_confirmation(user_response: str) -> dict:
    """Call with the user's yes/no reply. Executes or cancels the pending action."""
    global _pending_confirmation
    if _pending_confirmation is None:
        return _err("No pending action to confirm.")
    pc = _pending_confirmation
    _pending_confirmation = None
    if _is_affirmative_reply(user_response):
        if pc.fn:
            try:
                return pc.fn()
            except Exception as exc:
                return _err(str(exc))
        return _err("Action missing.")
    return {"success": False, "output": "Understood, standing down, sir.", "error": ""}


# ── Path helpers ──────────────────────────────────────────────────────────────

_USER_FOLDERS = frozenset({
    "documents", "downloads", "desktop", "pictures", "music",
    "videos", "onedrive", "appdata",
})

# When searching the user profile, prune heavy or irrelevant subtrees
_HOME_WALK_MAX_DEPTH = 8
_HOME_PRUNE_DIR_NAMES: frozenset[str] = frozenset(
    n.lower() for n in (
        "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        "npm-cache", ".yarn", ".nuget", "packages",  # can be huge
    )
)
# If dirpath contains these path fragments, do not descend (Windows)
_HOME_PRUNE_PATH_FRAGMENTS: tuple[str, ...] = (
    "\\appdata\\local\\packages\\",
    "\\appdata\\local\\pip\\",
    "\\node_modules\\",
)


def _default_create_parent() -> Path:
    """When no existing folder is found, new paths go here (not CWD)."""
    h = Path.home()
    key = (os.getenv("JARVIS_DEFAULT_CREATE_PARENT") or "Documents").strip()
    m = {
        "documents": h / "Documents",
        "desktop": h / "Desktop",
        "downloads": h / "Downloads",
        "home": h,
    }
    p = m.get(key.lower(), h / "Documents")
    try:
        return p if p.exists() or key.lower() == "home" else (h / "Documents")
    except OSError:
        return h / "Documents"


def _prune_home_walk_dirnames(pdir: Path, dirnames: list[str], home: Path) -> None:
    """In-place: drop dirs we should not descend into."""
    low = str(pdir).lower() + "\\"
    if any(frag in low for frag in _HOME_PRUNE_PATH_FRAGMENTS):
        dirnames.clear()
        return
    to_remove = {d for d in dirnames if d.lower() in _HOME_PRUNE_DIR_NAMES or d.startswith(".")}
    if not to_remove:
        return
    dirnames[:] = [d for d in dirnames if d not in to_remove]


def _find_all_exact_name_in_profile(home: Path, n_lower: str) -> list[Path]:
    """Find every directory directly under *home*'s tree whose *name* matches (casefold)."""
    home = home.resolve()
    if not n_lower or not home.exists():
        return []
    out: list[Path] = []
    try:
        for dirpath, dirnames, _ in os.walk(str(home), topdown=True):
            pdir = Path(dirpath)
            try:
                depth = len(pdir.relative_to(home).parts)
            except ValueError:
                depth = 0
            if depth > _HOME_WALK_MAX_DEPTH:
                dirnames.clear()
                continue
            _prune_home_walk_dirnames(pdir, dirnames, home)
            for dn in list(dirnames):
                if dn.lower() == n_lower:
                    c = pdir / dn
                    if c.is_dir():
                        out.append(c)
    except (PermissionError, OSError, ValueError):
        pass
    return out


def _pick_best_of_matches(cands: list[Path], home: Path) -> Path:
    """Shallowest under profile wins; then prefer a path that uses Documents/."""

    def _key(p: Path) -> tuple:
        p = p.resolve()
        try:
            d = len(p.relative_to(home).parts)
        except ValueError:
            d = 99
        doc = 0 if "Documents" in p.parts else 1
        return (d, doc, str(p).lower())

    return sorted(cands, key=_key)[0]


def _expand_path_string(s: str) -> str:
    """Expand Windows ``%VAR%`` (and simple ``$VAR`` on some shells), then ``~`` for Path."""
    t = (s or "").strip()
    if not t:
        return t
    t = os.path.expandvars(t)
    return str(Path(t).expanduser())


def _safe_path(path_str: str) -> Path:
    """Resolve path, correcting wrong C:\\Users\\<bad_name> guesses and relative user-folder refs."""
    if not path_str:
        return Path.home() / "jarvis_file.txt"

    p = Path(_expand_path_string(path_str))
    home = Path.home()
    parts = p.parts

    # Absolute path under C:\Users\<wrong_or_missing_username>\...
    if (len(parts) >= 3
            and parts[0].upper().rstrip("\\") in ("C:", "C:\\")
            and parts[1].lower() == "users"
            and parts[2].lower() != home.name.lower()
            and not (Path(parts[0]) / parts[1] / parts[2]).exists()):
        rest = parts[3:]
        if parts[2].lower() in _USER_FOLDERS:
            # Claude skipped the username (e.g. C:\Users\Documents\...)
            # Re-insert the real home: home\Documents\rest
            p = home / parts[2] / Path(*rest) if rest else home / parts[2]
        else:
            # Genuinely wrong username — drop it, keep the rest
            p = home / Path(*rest) if rest else home

    # Relative path starting with a known user folder (e.g. "Documents/file.txt")
    elif not p.is_absolute() and parts and parts[0].lower() in _USER_FOLDERS:
        p = home / Path(*parts)

    return p


def _find_folder(name: str) -> Path | None:
    """Find a folder by name: fast roots first, then full profile (Path.home()) tree.

    Profile search is depth-bounded and prunes e.g. node_modules, .git, big AppData
    package caches. Among multiple same-named folders, the **shallowest** wins, then
    paths under **Documents** are preferred.
    """
    home = Path.home()
    n = name.strip().lower()
    if not n:
        return None

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

    # Fast: immediate children of Documents / Desktop / Downloads / home
    for root in (
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home,
        home / "OneDrive" / "Documents",
        home / "OneDrive",
    ):
        if not root.exists():
            continue
        try:
            for p in root.iterdir():
                if p.is_dir() and p.name.lower() == n:
                    return p
        except (PermissionError, OSError):
            pass

    # Deeper: anywhere under the user profile (same drive as C:\\Users\\<you>…)
    cands = _find_all_exact_name_in_profile(home, n)
    if cands:
        uniq: dict[str, Path] = {}
        for c in cands:
            k = str(c.resolve())
            if k not in uniq:
                uniq[k] = c
        u = list(uniq.values())
        if len(u) == 1:
            return u[0]
        return _pick_best_of_matches(u, home)

    # Fuzzy (bounded depth) under Documents / Desktop / Downloads only
    candidates: list[tuple[float, Path]] = []
    for root in (home / "Documents", home / "Desktop", home / "Downloads"):
        root = root.resolve()
        if not root.exists():
            continue
        try:
            for dirpath, dirnames, _ in os.walk(str(root), topdown=True):
                pdir = Path(dirpath)
                try:
                    if len(pdir.relative_to(root).parts) > 5:
                        dirnames.clear()
                        continue
                except ValueError:
                    pass
                for dn in list(dirnames):
                    p = pdir / dn
                    if not p.is_dir():
                        continue
                    score = difflib.SequenceMatcher(None, p.name.lower(), n).ratio()
                    if score > 0.82:
                        candidates.append((score, p))
        except (PermissionError, OSError):
            pass

    if candidates:
        def _key(item: tuple[float, Path]) -> tuple:
            sc, pth = item
            under_docs = 1 if "Documents" in pth.parts else 0
            return (sc, under_docs, -len(pth.parts))

        candidates.sort(key=_key, reverse=True)
        return candidates[0][1]
    return None


def _resolve_file_operation_path(raw: str) -> Path:
    """Resolve a user path. The first segment is looked up as a folder name under the
    user profile (see *_find_folder*). If it does not exist, the path is rooted under
    *JARVIS_DEFAULT_CREATE_PARENT* (default: Documents), not the JARVIS process CWD."""
    if not raw or not str(raw).strip():
        return Path.home() / "jarvis_file.txt"
    s = _expand_path_string(str(raw).strip())
    p = Path(s.replace("\\", "/"))
    if p.is_absolute():
        return _safe_path(s)
    if not p.parts:
        return Path.home() / "jarvis_file.txt"
    first, *rest = p.parts
    if first in (".", ".."):
        return _safe_path(s)
    found = _find_folder(first)
    if found is not None:
        if not rest:
            return found
        return (found / Path(*rest))
    return _default_create_parent() / Path(*p.parts)


def _resolve_screenshot_path(save_param: str | None) -> tuple[str, str | None]:
    """
    Returns (resolved_save_path, folder_not_found_name | None).
    If second element is not None, caller should ask user to confirm folder creation.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"JARVIS_{ts}.png"

    if not save_param:
        return str(Path.home() / "Desktop" / fname), None

    p = Path(_expand_path_string(str(save_param)))

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

_WIN_APPID_PREFIX = "__WIN_APPID__:"
_WIN_PROTO_PREFIX = "__WIN_PROTO__:"

# Lazy cache for URL-protocol scan (avoids re-enumerating HKCR every command).
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
    """
    `stem` matches only as a full identifier, never as a short prefix of another
    product token (e.g. VS Code 'code' must not match the query 'codex').
    """
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
    """Fuzzy + token score for a human app name (StartApps / lnk) vs user phrase."""
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
    # Favour "microsoft store" vs "Microsoft Store" (near-identical) and high token overlap
    return min(1.0, 0.52 * r0 + 0.48 * j + (0.12 if tq.issubset(td) or td.issubset(tq) else 0.0))


def _score_query_vs_url_protocol(n_user: str, proto: str) -> float:
    """Map user text to a registered `ms-…` / app URL protocol; entirely data-driven."""
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
        _name_similarity(
            nq, _norm_query_compact(p_body_spaced)
        ),
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
    """
    System shell enumeration (Name + AppId). Empty if cmdlet unavailable
    or any failure — no hardcoded app list.
    """
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
            capture_output=True,
            text=True,
            timeout=25,
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
    """
    `shell:AppsFolder` via Shell.Application (often lists more UWP/Store apps
    than Get-StartApps alone). Returns (display name, AUMID path) pairs.
    """
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
            capture_output=True,
            text=True,
            timeout=60,
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
    """Deduplicate by app id, keep the longer (usually richer) display name."""
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
    r"""HKCR `ms-*` progid keys that declare a `URL Protocol` subkey — cached; no fixed list."""
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
    """Best registered `ms-…` URL protocol for the query (e.g. Store via ``ms-windows-store``)."""
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
    """Best (display_name, app_id) using token + string score (no per-app hardcoding)."""
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
    """Resolve an app: aliases → StartApps → Start-Menu lnk → PATH → registry → Program Files.

    StartApps / Start Menu run *before* ``shutil.which`` so a shell-installed GUI app
    (e.g. Claude Desktop) wins over a same-named CLI on PATH (e.g. ``claude`` / npm shim).
    """
    n_user = (name or "").strip()
    n_lower = n_user.lower()
    n_compact = _norm_query_compact(n_user)

    # 1. Built-in alias table
    alias = _WIN_ALIASES.get(n_lower)
    if alias:
        if shutil.which(alias):
            return alias
        return alias

    # 2. Windows shell: Get-StartApps + shell:AppsFolder COM merge (broader UWP coverage)
    start_rows = _get_all_startapp_rows()
    picked = _best_startapp_id(n_user, start_rows)
    if picked is not None:
        _disp, app_id = picked
        return f"{_WIN_APPID_PREFIX}{app_id}"

    # 3. Start Menu .lnk (strict scoring; no loose substring of exe stem in query)
    start_dirs: list[Path] = []
    appdata = os.environ.get("APPDATA", "")
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
                # r≈0.89 on 'codex' vs 'code' must not pass without a real word boundary
                if not ((r >= 0.9) or (r >= 0.72 and _exe_stem_matches_query(n_user, stem))):
                    continue
                if r > best_r_lnk:
                    best_r_lnk = r
                    best_lnk = str(lnk)
        except (PermissionError, OSError):
            pass
    if best_lnk and best_r_lnk >= 0.72:
        return best_lnk

    # 4. Direct PATH (after GUI-oriented resolution — see docstring)
    for candidate in [name, name + ".exe", n_lower, n_lower + ".exe", n_compact + ".exe"]:
        w = shutil.which(candidate)
        if w:
            return w

    # 5. Windows Registry — App Paths (strict similarity; no substring-only matches)
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

    # 6. Program Files and local app dirs (strict; avoid 'code' inside 'codex')
    prog_dirs = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path.home() / "AppData/Local/Programs",
        Path.home() / "AppData/Local",
    ]
    best_exe: str | None = None
    best_r_exe = 0.0
    for base in prog_dirs:
        if not base.exists():
            continue
        try:
            for exe in base.rglob("*.exe"):
                stem = exe.stem.lower()
                r = _name_similarity(n_compact, stem.replace(" ", ""))
                if (r >= 0.90) or (r >= 0.84 and _exe_stem_matches_query(n_user, stem)):
                    if r > best_r_exe:
                        best_r_exe = r
                        best_exe = str(exe)
        except (PermissionError, OSError):
            pass
    if best_exe and best_r_exe >= 0.8:
        return best_exe

    # 7. Registered ``ms-*`` URL protocol (HKCR scan) — covers Store and other shell protocols
    proto = _best_url_protocol(n_user)
    if proto:
        return _WIN_PROTO_PREFIX + proto

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
            if found.startswith(_WIN_APPID_PREFIX):
                app_uri = "shell:AppsFolder\\" + found[len(_WIN_APPID_PREFIX) :]
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
                pkey = found[len(_WIN_PROTO_PREFIX) :]
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
        _win_root = os.environ.get("SystemRoot", r"C:\Windows")
        _win_shutdown = os.path.join(_win_root, "System32", "shutdown.exe")
        cmds = {
            "windows": {
                "shutdown": [_win_shutdown, "/s", "/t", "5"],
                "restart":  [_win_shutdown, "/r", "/t", "5"],
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


def _strip_llm_path_placeholders(p: Path) -> Path:
    """The model often invents a `/.keep/jarvis_note` tail on folder paths; drop that."""
    try:
        parts = list(p.parts)
    except (TypeError, ValueError, OSError):
        return p
    for i, part in enumerate(parts):
        if part.casefold() == ".keep":
            return Path(*parts[:i]) if i else p
    return p


def _file_op_create_directory(params: dict) -> dict:
    """Create a single directory (and parents). Same confirm UI as create_file — no default file."""
    raw_path = params.get("path", "")
    s = (raw_path or "").strip()
    if not s:
        return _err("No path provided")
    path = _strip_llm_path_placeholders(_resolve_file_operation_path(s))
    if path.exists() and path.is_file():
        return _err(f"That path is already a file: {path.name}")
    try:
        target_display = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        target_display = str(path)
    prompt = (
        f"Create this folder, sir? (Parent folders are created if needed.)\n\n"
        f"Folder: {target_display}"
    )

    def _do_mkdir() -> dict:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return _ok(f"Created folder: {path.name}")
        except PermissionError:
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            return _err(str(exc))

    return request_confirmation(prompt, _do_mkdir)


def _handle_file_operation(action: str, params: dict, confirmed: bool = False) -> dict:
    raw_path = params.get("path", "")
    path     = _resolve_file_operation_path(raw_path) if raw_path else Path.home() / "jarvis_file.txt"
    dest     = _resolve_file_operation_path(params["destination"]) if params.get("destination") else None

    if action == "create_directory":
        return _file_op_create_directory(params)

    if action == "create_file":
        path = _strip_llm_path_placeholders(path)
        content = params.get("content", "")
        content_stripped = (content or "").strip() if isinstance(content, str) else ""
        raw_n = (raw_path or "").replace("\\", "/")
        has_trailing = len(raw_n) > 0 and raw_n.rstrip().endswith("/")

        if not path.suffix and not has_trailing and not content_stripped:
            return _file_op_create_directory({"path": str(path), **{k: v for k, v in params.items() if k != "path"}})

        if not path.suffix:
            path = path / "jarvis_note.txt"

        parent = path.parent
        try:
            target_display = str(path.resolve())
        except (OSError, ValueError, RuntimeError):
            target_display = str(path)
        try:
            folder_display = str(parent.resolve())
        except (OSError, ValueError, RuntimeError):
            folder_display = str(parent)

        lines = [f"File:  {target_display}", f"Folder: {folder_display}"]
        if not parent.exists():
            lines.append(
                "Note: that folder is not on disk yet — I can create it when you confirm."
            )
        path_summary = "\n".join(lines)

        def _do_create() -> dict:
            try:
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return _ok(f"Created: {path.name}")
            except PermissionError:
                return _err(f"Permission denied: {path}")
            except Exception as exc:
                return _err(str(exc))

        from core.personality import ask as _ask

        return request_confirmation(_ask("create_file", path_summary), _do_create)

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
            found = _find_existing_item(path)
            if found:
                path = found
            else:
                return _err(f"Cannot find {path.name!r} — check the name and try again.")
        try:
            full_path_str = str(path.resolve())
        except (OSError, ValueError):
            full_path_str = str(path)
        is_dir = path.is_dir()
        kind = "Folder" if is_dir else "File"
        lines = [f"{kind}: {full_path_str}"]
        if is_dir:
            try:
                n = sum(1 for _ in path.rglob("*"))
                lines.append(f"Contains: {n} item(s) — all will be permanently removed")
            except (PermissionError, OSError):
                lines.append("Note: all contents will be permanently removed")

        item_desc = "\n".join(lines)

        def _do_delete() -> dict:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return _ok(f"Deleted: {path.name}")
            except PermissionError:
                msg = f"Permission denied: {path.name}"
                return {"success": False, "output": msg, "error": msg}
            except Exception as exc:
                msg = str(exc)
                return {"success": False, "output": msg, "error": msg}

        from core.personality import ask as _ask
        if confirmed:
            return _do_delete()
        return request_confirmation(_ask("delete_file", item_desc), _do_delete)

    if action == "rename_file":
        if not path.exists():
            found = _find_existing_item(path)
            if found:
                path = found
            else:
                return _err(f"Cannot find {path.name!r} — check the name and try again.")
        new_name_raw = (params.get("new_name") or params.get("destination") or "").strip()
        if not new_name_raw:
            return _err("No new name provided for rename.")
        new_filename = Path(new_name_raw).name or new_name_raw
        dest_path = path.parent / new_filename
        try:
            loc_str = str(path.parent.resolve())
        except (OSError, ValueError):
            loc_str = str(path.parent)
        rename_desc = f"From: {path.name}\nTo:   {new_filename}\nIn:   {loc_str}"

        def _do_rename() -> dict:
            try:
                if dest_path.exists():
                    msg = f"'{new_filename}' already exists in that location"
                    return {"success": False, "output": msg, "error": msg}
                path.rename(dest_path)
                return _ok(f"Renamed to {new_filename}")
            except PermissionError:
                msg = "Permission denied"
                return {"success": False, "output": msg, "error": msg}
            except Exception as exc:
                msg = str(exc)
                return {"success": False, "output": msg, "error": msg}

        from core.personality import ask as _ask
        return request_confirmation(_ask("rename_file", rename_desc), _do_rename)

    if action == "move_file":
        if not path.exists():
            found = _find_existing_item(path)
            if found:
                path = found
        # No path separators: either a well-known profile folder (Downloads, …) or
        # a new name in the same directory as the source. Do not clobber a resolved
        # folder (e.g. _find_folder("Downloads") → home/Downloads) with path.parent / "Downloads".
        raw_dest_str = (params.get("destination") or "").strip()
        if (
            raw_dest_str
            and "/" not in raw_dest_str
            and "\\" not in raw_dest_str
            and _find_folder(raw_dest_str) is None
        ):
            dest = path.parent / raw_dest_str
        if dest is None:
            return _err("No destination provided")
        try:
            shutil.move(str(path), str(dest))
            return _ok(f"Moved {path.name} → {dest.name}")
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


def _find_existing_item(path: Path) -> Path | None:
    """Find an existing file or folder when the exact resolved path does not exist.

    Strategy:
    1. Walk up to the nearest existing ancestor and rglob for path.name inside it.
       This handles "jarvis-project/executor.py" where executor.py lives in core/.
    2. Fall back to a broad rglob across Desktop / Documents / Downloads / home.
    """
    target = path.name
    if not target:
        return None

    # Step 1: nearest existing ancestor
    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.exists() and ancestor.is_dir():
            try:
                for found in ancestor.rglob(target):
                    if found.exists():
                        return found
            except (PermissionError, OSError):
                pass
            break
        ancestor = ancestor.parent

    # Step 2: broad fallback
    for root in (
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home(),
    ):
        if not root.exists():
            continue
        try:
            for found in root.rglob(target):
                if found.exists():
                    return found
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
        return browser.close_tab(
            title_contains=(
                (params.get("title_contains") or params.get("title", "") or "")
            ).strip(),
            url_contains=(
                (params.get("url_contains") or params.get("url_match", "") or "")
            ).strip(),
            match=(
                (params.get("match") or params.get("tab") or params.get("target", "") or "")
            ).strip(),
        )

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
    # delete_file is confirmed executor-side (shows resolved path in the card)
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
    last_step_intent  = ""
    last_step_action  = ""
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
        if sub.get("needs_confirmation"):
            # Same dict as a direct `create_file` / folder prompt — main shows the
            # confirm card. `_PENDING["fn"]` was set by the nested `dispatch` call.
            # After the user confirms, only that step's callback runs; remaining
            # workflow steps in *this* invocation are skipped (no resume queue yet).
            return sub
        results.append(f"Step {i}: {'OK' if sub['success'] else 'FAIL'} — {sub['output'] or sub['error']}")
        if sub["success"]:
            last_step_intent = (step.get("intent") or "").strip()
            last_step_action = (step.get("action") or "").strip()
        if not sub["success"]:
            all_ok = False
            break

    if workflow_id and all_ok:
        workflow_library.mark_run(workflow_id)

    summary = "\n".join(results)
    if not all_ok:
        return _err(summary)
    out: dict = _ok(summary)
    if last_step_intent and last_step_action:
        out["last_step_intent"] = last_step_intent
        out["last_step_action"] = last_step_action
    return out


# ── Reminders ─────────────────────────────────────────────────────────────────
#
# Pure message reminders: fire `status_changed` with REMINDER: …
# Action reminders: optional `parameters.run` = { intent, action, parameters }
# — validated and executed on the Qt main thread via `signals.reminder_action`.

_active_reminders: dict[str, threading.Timer] = {}
_reminder_meta: dict[str, dict[str, Any]] = {}


def _format_run_summary(run: dict[str, Any]) -> str:
    """Short label for transcript and list_reminders."""
    intent = run.get("intent", "")
    act = run.get("action", "")
    p = run.get("parameters") or {}
    if intent == "open_app":
        if act == "open_browser":
            return f"open browser ({p.get('browser', 'default')})"
        if act == "open_url":
            return f"open URL"
        return f"{act}: {p.get('app_name', p.get('url', ''))}"[:80]
    if intent == "search_web":
        return f"search: {p.get('query', '')}"[:80]
    if intent == "system_control":
        return f"{act}"
    if intent == "browser_automation":
        return f"{act}"
    if intent == "read_screen":
        return f"{act}"
    if intent == "jarvis_meta":
        return f"{act}"
    return f"{intent}/{act}"


def _is_schedulable_reminder_action(intent: str, act: str) -> bool:
    """Actions that may run unattended when a timer fires (no extra user click)."""
    if not intent or not act:
        return False
    if intent in (
        "code_execution",
        "automation_task",
        "reminder_task",
        "file_operation",
        "close_app",
        "type_text",
        "control_mouse",
    ):
        return False
    if (intent, act) in _DANGEROUS_STEPS:
        return False
    if (intent, act) in _CONFIRMATION_REQUIRED_ACTIONS:
        return False
    if intent == "system_control":
        return act in (
            "screenshot",
            "volume_up",
            "volume_down",
            "volume_mute",
            "lock_screen",
            "brightness_up",
            "brightness_down",
        )
    if intent == "jarvis_meta":
        return act in ("tell_time", "tell_date", "status_report", "list_voices")
    if intent == "browser_automation":
        return act in (
            "navigate",
            "new_tab",
            "read_page",
            "fill_form",
            "extract_text",
            "click_element",
            "screenshot",
        )
    if intent in ("open_app", "search_web", "read_screen"):
        return True
    return False


def _validate_reminder_run(run: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return (normalised run dict, error message)."""
    if run is None:
        return None, None
    if not isinstance(run, dict):
        return None, "parameters.run must be an object"
    intent = str(run.get("intent", "")).strip()
    act = str(run.get("action", "")).strip()
    params = run.get("parameters")
    if not isinstance(params, dict):
        params = {}
    if not _is_schedulable_reminder_action(intent, act):
        return None, (
            f"Scheduled action not allowed for '{intent}/{act}' — "
            "use a safe action (open app, search, screenshot, navigate, etc.)."
        )
    return {"intent": intent, "action": act, "parameters": params}, None


def _handle_reminder_task(action: str, params: dict) -> dict:
    if action == "set_reminder":
        msg = str(params.get("message", "Reminder")).strip() or "Reminder"
        delay = max(5, int(params.get("delay_seconds", 60)))
        run_raw = params.get("run")
        run_norm, verr = _validate_reminder_run(run_raw)
        if verr:
            return _err(verr)

        sched_conf = params.get("schedule_confidence")
        try:
            sc = float(sched_conf) if sched_conf is not None else 0.92
        except (TypeError, ValueError):
            sc = 0.92
        sc = max(0.0, min(1.0, sc))

        rid = str(params.get("reminder_id") or uuid.uuid4().hex[:12])

        def _fire() -> None:
            _active_reminders.pop(rid, None)
            meta = _reminder_meta.pop(rid, None) or {}
            m = meta.get("message", msg)
            r = meta.get("run")
            try:
                from core.signals import signals
                if r and isinstance(r, dict):
                    signals.reminder_action.emit(
                        {
                            "reminder_id": rid,
                            "message": m,
                            "run": r,
                            "schedule_confidence": float(meta.get("schedule_confidence", 0.92)),
                        }
                    )
                else:
                    signals.status_changed.emit(f"REMINDER: {m}")
            except Exception:
                pass

        t = threading.Timer(delay, _fire)
        t.daemon = True
        t.start()
        _active_reminders[rid] = t
        _reminder_meta[rid] = {
            "message": msg,
            "run": run_norm,
            "schedule_confidence": sc,
        }
        mins = delay // 60
        secs = delay % 60
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        if run_norm:
            summ = _format_run_summary(run_norm)
            return _ok(f"In {time_str}: {summ}")
        return _ok(f"In {time_str}: {msg}")

    if action == "cancel_reminder":
        want = str(params.get("message", "")).strip()
        if not want:
            return _err("No message provided for cancel_reminder.")
        cancelled = 0
        to_del: list[str] = []
        for rid, meta in list(_reminder_meta.items()):
            if str(meta.get("message", "")).strip() == want:
                to_del.append(rid)
        for rid in to_del:
            t = _active_reminders.pop(rid, None)
            _reminder_meta.pop(rid, None)
            if t:
                t.cancel()
                cancelled += 1
        if cancelled:
            return _ok(
                f"Cancelled {cancelled} reminder(s) for: {want}"
                if cancelled > 1
                else f"Reminder cancelled: {want}"
            )
        return _err(f"No active reminder matching: {want}")

    if action == "list_reminders":
        if not _reminder_meta:
            return _ok("No active reminders.")
        lines: list[str] = []
        for rid, meta in _reminder_meta.items():
            m = str(meta.get("message", ""))
            r = meta.get("run")
            if r:
                lines.append(f"- [{rid}] {m} → {_format_run_summary(r)}")
            else:
                lines.append(f"- [{rid}] {m}")
        return _ok("\n".join(lines))

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
        parts = [
            f"CPU {cpu:.0f}%",
            f"memory {mem.percent:.0f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)",
        ]
        try:
            bat = psutil.sensors_battery()
        except (AttributeError, NotImplementedError):
            bat = None
        if bat is not None and bat.percent is not None:
            plug = "plugged in" if bat.power_plugged else "on battery"
            parts.append(f"battery {bat.percent:.0f}% ({plug})")
        return _ok(", ".join(parts))
    if action == "conversational":
        # Check page cache for "what does it say" queries
        cached = get_page_cache()
        if cached:
            return _ok(cached[:800])
        return _ok("")
    if action == "list_voices":
        from core.voice import _EL_VOICES
        _LABELS = {
            "male-british":         "George  — deep, warm British",
            "male-american":        "Adam    — neutral American",
            "female-british":       "Rachel  — warm British female",
            "male-broadcast":       "Daniel  — strong broadcast voice",
            "male-resonant":        "Brian   — resonant, narration",
            "male-smooth":          "Eric    — smooth, conversational",
            "male-gravelly":        "Callum  — gravelly, distinctive",
            "male-casual":          "Chris   — natural, down-to-earth",
            "male-australian":      "Charlie — energetic Australian",
            "female-professional":  "Sarah   — professional, warm",
            "female-british-clear": "Alice   — British female, clear",
            "female-british-warm":  "Lily    — British female, warm",
            "female-american":      "Matilda — professional American female",
        }
        current = config.tts_voice
        lines = ["Available voices (* = current):"]
        for key in _EL_VOICES:
            label = _LABELS.get(key, key)
            marker = " *" if key == current else ""
            lines.append(f"  • {label}{marker}")
        return _ok("\n".join(lines))

    if action == "change_voice":
        # Map natural names / aliases → config key
        _VOICE_ALIASES: dict[str, str] = {
            # keys — accept exact config key
            "male-british":         "male-british",
            "male-american":        "male-american",
            "female-british":       "female-british",
            "male-broadcast":       "male-broadcast",
            "male-resonant":        "male-resonant",
            "male-smooth":          "male-smooth",
            "male-gravelly":        "male-gravelly",
            "male-casual":          "male-casual",
            "male-australian":      "male-australian",
            "female-professional":  "female-professional",
            "female-british-clear": "female-british-clear",
            "female-british-warm":  "female-british-warm",
            "female-american":      "female-american",
            # name aliases
            "george":    "male-british",
            "adam":      "male-american",
            "adams":     "male-american",  # common STT / typo
            "rachel":    "female-british",
            "daniel":    "male-broadcast",
            "brian":     "male-resonant",
            "eric":      "male-smooth",
            "callum":    "male-gravelly",
            "chris":     "male-casual",
            "charlie":   "male-australian",
            "sarah":     "female-professional",
            "alice":     "female-british-clear",
            "lily":      "female-british-warm",
            "matilda":   "female-american",
            # natural language aliases
            "british":      "male-british",
            "american":     "male-american",
            "female":       "female-british",
            "broadcast":    "male-broadcast",
            "deep":         "male-resonant",
            "smooth":       "male-smooth",
            "gravelly":     "male-gravelly",
            "casual":       "male-casual",
            "australian":   "male-australian",
            "aussie":       "male-australian",
            "professional": "female-professional",
        }
        _VOICE_LABELS: dict[str, str] = {
            "male-british":         "George (British male)",
            "male-american":        "Adam (American male)",
            "female-british":       "Rachel (British female)",
            "male-broadcast":       "Daniel (broadcast, professional)",
            "male-resonant":        "Brian (resonant, narration)",
            "male-smooth":          "Eric (smooth, conversational)",
            "male-gravelly":        "Callum (gravelly, distinctive)",
            "male-casual":          "Chris (casual, natural American)",
            "male-australian":      "Charlie (Australian, energetic)",
            "female-professional":  "Sarah (professional, warm)",
            "female-british-clear": "Alice (British female, clear)",
            "female-british-warm":  "Lily (British female, warm)",
            "female-american":      "Matilda (American female, professional)",
        }
        raw = (params.get("voice") or "").strip().lower()
        key = _VOICE_ALIASES.get(raw)
        if not key:
            available = ", ".join(_VOICE_LABELS.values())
            return _err(f"Unknown voice {raw!r}. Available: {available}")
        config.tts_voice = key
        config.save()
        label = _VOICE_LABELS[key]
        return _ok(f"Voice set to {label}")

    if action in ("quit_application", "close_jarvis"):
        # Main window speaks `response` then calls QApplication.quit() on a timer
        return {"success": True, "output": "", "error": "", "quit_application": True}
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
        if intent == "file_operation":
            return handler(action, params, confirmed=confirmed)
        return handler(action, params)
    except Exception as exc:
        if config.debug_mode:
            print(f"[executor] Unhandled error in {intent}/{action}: {exc}")
        return _err(str(exc))
