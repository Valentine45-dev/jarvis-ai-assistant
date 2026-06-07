"""Browser session core: shared constants + lifecycle (R2-17c split).

Part of the ``core/browser`` package. Houses the module-level constants and
the ``_SessionBase`` lifecycle class. The sibling mixins (interaction, picker,
tabs) import constants *from* this module; this module imports none of them,
so there is no circular import.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from core.handlers.shared import _err

# Persistent browser profile so cookies/history survive across JARVIS runs. A
# fresh new_context() every launch looked like an anonymous throwaway browser to
# Google → constant "unusual traffic" reCAPTCHA. A warmed persistent profile
# (plus the anti-automation flag below) looks like a returning human and gets
# challenged far less. Gitignored; lives under data/ with the other runtime state.
#
# Each engine gets its OWN profile dir so they can run concurrently without a
# SingletonLock clash, and so switching engines never disturbs another engine's
# cookies/session. Chrome keeps the original path (data/browser_profile) so its
# already-warmed, logged-in profile is preserved untouched.
_BROWSER_PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "browser_profile"

# Supported engines and their per-engine profile directories. Order doubles as
# the auto-detect preference order (chrome → edge → firefox).
_ENGINE_KEYS: tuple[str, ...] = ("chrome", "edge", "firefox")
_DEFAULT_ENGINE = "chrome"
_PROFILE_DIRS: dict[str, Path] = {
    "chrome":  _BROWSER_PROFILE_DIR,
    "edge":    _BROWSER_PROFILE_DIR.parent / "browser_profile_edge",
    "firefox": _BROWSER_PROFILE_DIR.parent / "browser_profile_firefox",
}

# Chromium-family stealth flags — shared verbatim by Chrome and Edge (Edge IS
# Chromium, so every flag applies identically). Firefox uses prefs instead.
_CHROMIUM_ARGS: list[str] = [
    "--force-renderer-accessibility",
    "--disable-blink-features=AutomationControlled",
]
# Drop two Playwright defaults:
#  --enable-automation: removes the "Chrome is being controlled by automated
#    test software" infobar + an automation signal.
#  --no-sandbox: Playwright passes it by default; with --enable-automation gone,
#    Chrome surfaces the scary "unsupported flag, security will suffer" banner.
#    Dropping it removes the banner AND re-enables the sandbox (more secure).
_CHROMIUM_IGNORE_DEFAULT_ARGS: list[str] = ["--enable-automation", "--no-sandbox"]

# Firefox can't take Chromium switches; it's tuned via about:config prefs.
_FIREFOX_USER_PREFS: dict[str, object] = {
    "dom.webdriver.enabled": False,   # hide navigator.webdriver
    "useAutomationExtension": False,
}

# Standard install locations probed for engine-availability detection (Windows
# first since that's the primary target; shutil.which covers PATH + other OSes).
_PROGRAM_FILES = os.environ.get("PROGRAMFILES", r"C:\Program Files")
_PROGRAM_FILES_X86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
_CHROME_WIN_PATHS: tuple[str, ...] = (
    rf"{_PROGRAM_FILES}\Google\Chrome\Application\chrome.exe",
    rf"{_PROGRAM_FILES_X86}\Google\Chrome\Application\chrome.exe",
    rf"{_LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
)
_EDGE_WIN_PATHS: tuple[str, ...] = (
    rf"{_PROGRAM_FILES_X86}\Microsoft\Edge\Application\msedge.exe",
    rf"{_PROGRAM_FILES}\Microsoft\Edge\Application\msedge.exe",
)


def _find_chromium_channel(engine: str) -> str | None:
    """Return a path/command for a system-installed Chrome/Edge, or None.

    Used by availability detection (and 'auto' engine selection). Checks PATH via
    shutil.which first (covers macOS/Linux command names), then the standard
    Windows install locations.
    """
    if engine == "chrome":
        for cmd in ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            hit = shutil.which(cmd)
            if hit:
                return hit
        win_paths: tuple[str, ...] = _CHROME_WIN_PATHS
    else:  # edge
        for cmd in ("msedge", "microsoft-edge", "microsoft-edge-stable"):
            hit = shutil.which(cmd)
            if hit:
                return hit
        win_paths = _EDGE_WIN_PATHS
    for p in win_paths:
        if p and Path(p).exists():
            return p
    return None


def _playwright_firefox_present(pw) -> bool:
    """True when Playwright's bundled Firefox build is installed on disk.

    Playwright drives its OWN Firefox build (downloaded via `playwright install
    firefox`), NOT the user's system Firefox — so this checks the driver's
    executable_path. When the driver isn't started yet (pw is None) we can't
    know cheaply, so we answer optimistically and let the launch error guide the
    user; 'auto' mode only reaches firefox after chrome/edge both fail anyway.
    """
    try:
        if pw is not None:
            ep = pw.firefox.executable_path
            return bool(ep and Path(ep).exists())
    except Exception:
        pass
    return True


_TIMEOUT = 15_000   # ms — max wait per page/locator operation
_SUBTRY    = 4_000   # ms per fallback locator attempt

# Snapshot-driven element picker (find_and_act)
_MAX_SNAPSHOT_NODES = 400
_NAME_TRUNCATE      = 120
_HREF_TRUNCATE      = 60
_HAIKU_MODEL        = "claude-haiku-4-5-20251001"
_HAIKU_TIMEOUT_S    = 10

# Interactive roles get priority emission when the node budget is tight.
_INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "button", "link", "textbox", "combobox", "checkbox", "radio",
    "menuitem", "menuitemcheckbox", "menuitemradio",
    "tab", "switch", "searchbox", "slider", "spinbutton",
    "option", "treeitem",
})


# Search boxes — shared by fill_form and click (Enter submit fallback)
_SEARCH_INPUT_SELECTORS: list[str] = [
    "input#search",
    "input[name='search_query']",
    "ytd-searchbox input",
    "ytd-masthead ytd-searchbox input",
    "input[name='q']",
    "textarea[name='q']",
    "[role='searchbox']",
    "input[type='search']",
    "[aria-label*='Search']",
    "input[placeholder*='earch']",
    "#search-input",
    ".search-input",
]

# Click targets that submit a search (IDs change; order: specific → broad)
_SEARCH_SUBMIT_SELECTORS: list[str] = [
    "button#search-icon-legacy",
    "#search-icon-legacy",
    "ytd-masthead #search button#search-icon-legacy",
    "ytd-masthead #search #button",
    "ytd-masthead ytd-searchbox + button",
    "ytd-masthead form[action*='results'] button",
    "yt-icon-button#search",
    "button[aria-label*='Search']",
    "button[aria-label*='search']",
    "button[title*='Search']",
    "[role='button'][aria-label*='search']",
]


class _EngineSession:
    """One live browser engine's handles. Several can coexist (Chrome + Edge +
    Firefox); the active one is selected by ``_SessionBase._active``."""

    __slots__ = ("engine", "context", "page", "ready", "start_err", "ref_map")

    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.context = None
        self.page = None
        self.ready = False
        self.start_err = ""
        # Populated by snapshot(); consumed by find_and_act() after Haiku picks a ref.
        self.ref_map: dict[int, dict] = {}


class _SessionBase:
    """Owns the Playwright driver + lock and the start/stop/recovery lifecycle.

    CONCURRENT MODEL: one Playwright driver (``self._pw``) drives a *registry* of
    per-engine sessions (``self._sessions``), all on the thread that started the
    driver. ``self._active`` names the engine current commands hit. Switching
    engines just re-points ``_active`` — nothing is closed, no tabs are lost.

    The mixins (interaction/picker/tabs) read & write ``self._page`` /
    ``self._context`` / ``self._ready`` / ``self._ref_map`` directly; those are
    PROPERTIES that route to the active engine's ``_EngineSession``, so every
    mixin works unchanged regardless of which engine is active.
    """

    def __init__(self) -> None:
        # RLock so _recover() can re-enter while the caller already holds the lock
        self._lock = threading.RLock()
        self._pw      = None   # playwright driver handle (shared by all engines)
        self._pw_err  = ""     # driver-start failure message, if any
        self._browser = None   # persistent contexts own the browser → always None
        self._sessions: dict[str, _EngineSession] = {}
        self._active = ""      # active engine key ("" until first start)

    # ── Active-engine routing properties (keep mixins engine-agnostic) ─────────

    def _act(self) -> _EngineSession | None:
        return self._sessions.get(self._active)

    @property
    def _page(self):
        s = self._act()
        return s.page if s else None

    @_page.setter
    def _page(self, value) -> None:
        s = self._act()
        if s:
            s.page = value

    @property
    def _context(self):
        s = self._act()
        return s.context if s else None

    @_context.setter
    def _context(self, value) -> None:
        s = self._act()
        if s:
            s.context = value

    @property
    def _ready(self) -> bool:
        s = self._act()
        return bool(s and s.ready)

    @_ready.setter
    def _ready(self, value) -> None:
        s = self._act()
        if s:
            s.ready = bool(value)

    @property
    def _ref_map(self) -> dict[int, dict]:
        s = self._act()
        return s.ref_map if s else {}

    @_ref_map.setter
    def _ref_map(self, value) -> None:
        s = self._act()
        if s:
            s.ref_map = value

    @property
    def _start_err(self) -> str:
        s = self._act()
        return s.start_err if s else self._pw_err

    @property
    def active_engine(self) -> str:
        """The engine current commands operate on ('' before first start)."""
        return self._active

    # ── Engine resolution + availability ──────────────────────────────────────

    def _configured_engine(self) -> str:
        try:
            from config.settings import config as _cfg
            return (getattr(_cfg, "browser_engine", "") or _DEFAULT_ENGINE).strip().lower()
        except Exception:
            return _DEFAULT_ENGINE

    def _resolve_engine(self, engine: str | None) -> str:
        """Map a requested engine (or None / 'auto') to a concrete engine key."""
        eng = (engine or "").strip().lower()
        if eng in _ENGINE_KEYS:
            return eng
        if not eng:
            eng = self._configured_engine()
        if eng == "auto":
            return self._first_available_engine()
        return eng if eng in _ENGINE_KEYS else _DEFAULT_ENGINE

    def _engine_available(self, engine: str) -> tuple[bool, str]:
        """(is_installed, friendly_reason_if_not). Cheap — no browser launched."""
        engine = (engine or "").strip().lower()
        if engine in ("chrome", "edge"):
            if _find_chromium_channel(engine):
                return True, ""
            nice = "Chrome" if engine == "chrome" else "Microsoft Edge"
            return False, f"{nice} isn't installed on this device."
        if engine == "firefox":
            if _playwright_firefox_present(self._pw):
                return True, ""
            return False, "Firefox engine isn't installed — run: playwright install firefox"
        return False, f"Unknown browser engine: {engine!r}"

    def _first_available_engine(self) -> str:
        for eng in _ENGINE_KEYS:
            ok, _ = self._engine_available(eng)
            if ok:
                return eng
        return _DEFAULT_ENGINE

    # ── Launch config (the ONLY engine-specific code) ─────────────────────────

    def _launch_config(self, engine: str) -> tuple[str, Path, dict]:
        """(playwright_type_name, profile_dir, launch_kwargs) for an engine.

        Chrome & Edge are both Chromium → identical kwargs but for the channel.
        Firefox is a different Playwright browser type with its own prefs and no
        Chromium switches (passing them would raise on launch).
        """
        profile_dir = _PROFILE_DIRS.get(engine, _BROWSER_PROFILE_DIR)
        if engine in ("chrome", "edge"):
            return "chromium", profile_dir, {
                "channel": "chrome" if engine == "chrome" else "msedge",
                "headless": False,
                "args": list(_CHROMIUM_ARGS),
                "ignore_default_args": list(_CHROMIUM_IGNORE_DEFAULT_ARGS),
            }
        if engine == "firefox":
            return "firefox", profile_dir, {
                "headless": False,
                "firefox_user_prefs": dict(_FIREFOX_USER_PREFS),
            }
        # Unknown → behave as chrome.
        return self._launch_config("chrome")

    def _friendly_start_error(self, engine: str, msg: str) -> str:
        low = msg.lower()
        if "already in use" in low or "singletonlock" in low:
            return (
                "Browser profile is in use — close other JARVIS instances "
                "(or delete the data/browser_profile* folder) and try again."
            )
        if engine == "firefox" and ("executable doesn't exist" in low or "playwright install" in low):
            return "Firefox engine isn't installed — run: playwright install firefox"
        if engine == "edge" and ("executable doesn't exist" in low or "msedge" in low or "channel" in low):
            return "Microsoft Edge not found — install Edge, then try again."
        if engine == "chrome" and ("executable doesn't exist" in low or "chrome" in low):
            return (
                "Chrome not found — install Google Chrome "
                "from https://www.google.com/chrome"
            )
        if "playwright install" in low:
            return f"Playwright driver missing — run: playwright install {engine}"
        return f"Browser failed to start: {msg}"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _ensure_pw(self) -> None:
        """Start the shared Playwright driver once. Records _pw_err on failure."""
        if self._pw is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._pw_err = ""
        except Exception as exc:
            self._pw = None
            self._pw_err = f"Playwright driver failed to start: {exc}"

    def _launch_into(self, sess: _EngineSession) -> None:
        """Launch one engine into its session. Persistent context (not launch()+
        new_context()): keeps cookies/history across runs so the engine looks like
        a returning human. The context owns the browser, so _browser stays None."""
        engine = sess.engine
        try:
            type_name, profile_dir, kwargs = self._launch_config(engine)
            profile_dir.mkdir(parents=True, exist_ok=True)
            browser_type = getattr(self._pw, type_name)
            sess.context = browser_type.launch_persistent_context(str(profile_dir), **kwargs)
            sess.page = sess.context.pages[0] if sess.context.pages else sess.context.new_page()
            sess.ready = True
            sess.start_err = ""
        except Exception as exc:
            sess.ready = False
            sess.start_err = self._friendly_start_error(engine, str(exc))

    def start(self, engine: str | None = None) -> None:
        """Launch (or focus) a browser engine and make it active.

        ``engine``: 'chrome' | 'edge' | 'firefox' | 'auto' | None. None/'' uses
        the configured default (config.browser_engine, default 'chrome'). If the
        engine is already running it's just made active (no relaunch). Other live
        engines are left untouched. Safe to call repeatedly. Must run on the
        thread that owns the Playwright driver (the Qt main thread)."""
        with self._lock:
            eng = self._resolve_engine(engine)
            existing = self._sessions.get(eng)
            if existing and existing.ready:
                self._active = eng
                return
            self._ensure_pw()
            sess = _EngineSession(eng)
            self._sessions[eng] = sess
            self._active = eng
            if self._pw is None:
                sess.ready = False
                sess.start_err = self._pw_err or "Playwright driver unavailable"
                return
            self._launch_into(sess)

    def stop(self) -> None:
        """Close ALL engines and the driver. Safe to call even when not started."""
        with self._lock:
            for sess in list(self._sessions.values()):
                for obj in (sess.page, sess.context):
                    try:
                        if obj is not None:
                            obj.close()
                    except Exception:
                        pass
            try:
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass
            self._sessions = {}
            self._active = ""
            self._pw = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def start_error(self) -> str:
        """Public read of the most recent start() failure message (empty if none)."""
        return self._start_err

    def _not_ready(self) -> dict | None:
        """Return _err if the active engine isn't ready after one auto-restart
        attempt, else None. RLock lets _recover() re-enter while the caller holds it.
        """
        if self._ready:
            return None
        # Auto-restart once — covers an external close / crash of the active engine.
        self._recover()
        if self._ready:
            return None
        return _err(self._start_err or "Browser not started — call browser.start() first")

    def _recover(self) -> bool:
        """Relaunch the ACTIVE engine after it was closed externally, leaving the
        other live engines alone. Called from within the lock (RLock re-entrant)."""
        eng = self._active
        if not eng:
            # Nothing active yet — bring up the default engine.
            self.start()
            return self._ready
        old = self._sessions.get(eng)
        if old is not None:
            for obj in (old.page, old.context):
                try:
                    if obj is not None:
                        obj.close()
                except Exception:
                    pass
        self._ensure_pw()
        sess = _EngineSession(eng)
        self._sessions[eng] = sess
        if self._pw is None:
            sess.start_err = self._pw_err or "Playwright driver unavailable"
            return False
        self._launch_into(sess)
        return self._ready

    def _with_recovery(self, label: str, fn):
        """Run a Playwright op; on 'closed' errors, restart Chrome once + retry.

        Caller must hold self._lock. fn() should perform the op and return an
        _ok/_err dict. Mirrors the recovery branch in navigate() so other ops
        survive an external Chrome close.
        """
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            if "closed" in msg.lower():
                self._ready = False
                if self._recover():
                    try:
                        return fn()
                    except Exception as exc2:
                        return _err(str(exc2))
                return _err("Browser session lost — Chrome was closed externally")
            if "timeout" in msg.lower():
                return _err(f"{label} timed out: {msg}")
            return _err(msg)
