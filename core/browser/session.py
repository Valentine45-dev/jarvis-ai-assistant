"""Browser session core: shared constants + lifecycle (R2-17c split).

Part of the ``core/browser`` package. Houses the module-level constants and
the ``_SessionBase`` lifecycle class. The sibling mixins (interaction, picker,
tabs) import constants *from* this module; this module imports none of them,
so there is no circular import.
"""

from __future__ import annotations

import threading
from pathlib import Path

from core.handlers.shared import _err

# Persistent Chrome profile so cookies/history survive across JARVIS runs. A
# fresh new_context() every launch looked like an anonymous throwaway browser to
# Google → constant "unusual traffic" reCAPTCHA. A warmed persistent profile
# (plus the anti-automation flag below) looks like a returning human and gets
# challenged far less. Gitignored; lives under data/ with the other runtime state.
_BROWSER_PROFILE_DIR = Path(__file__).resolve().parents[2] / "data" / "browser_profile"

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


class _SessionBase:
    """Owns the Playwright handles + lock and the start/stop/recovery lifecycle."""

    def __init__(self) -> None:
        # RLock so _recover() can re-enter while the caller already holds the lock
        self._lock = threading.RLock()
        self._pw        = None  # playwright context manager handle
        self._browser   = None
        self._context   = None
        self._page      = None
        self._ready     = False
        self._start_err = ""
        # Populated by snapshot(); consumed by find_and_act() after Haiku picks a ref.
        self._ref_map: dict[int, dict] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch Chrome. No-op if already running. Safe to call from any thread."""
        with self._lock:
            if self._ready:
                return
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                _BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                # Persistent context (not launch()+new_context()): keeps cookies
                # /history across runs so Google sees a returning human, and the
                # AutomationControlled flag hides navigator.webdriver — both cut
                # the "unusual traffic" reCAPTCHA rate. It owns the browser, so
                # there's no separate Browser handle; stop() closes the context.
                self._context = self._pw.chromium.launch_persistent_context(
                    str(_BROWSER_PROFILE_DIR),
                    channel="chrome",
                    headless=False,
                    args=[
                        "--force-renderer-accessibility",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    # Drop two Playwright defaults:
                    #  --enable-automation: removes the "Chrome is being controlled
                    #    by automated test software" infobar + an automation signal.
                    #  --no-sandbox: Playwright passes it by default; with
                    #    --enable-automation gone, Chrome surfaces the scary
                    #    "unsupported flag, security will suffer" banner. Dropping
                    #    it removes the banner AND re-enables Chrome's sandbox
                    #    (more secure) — verified to still launch on Windows.
                    ignore_default_args=["--enable-automation", "--no-sandbox"],
                )
                self._browser = None
                self._page = (
                    self._context.pages[0]
                    if self._context.pages
                    else self._context.new_page()
                )
                self._ready     = True
                self._start_err = ""
            except Exception as exc:
                self._ready = False
                msg = str(exc)
                if "already in use" in msg.lower() or "singletonlock" in msg.lower():
                    self._start_err = (
                        "Browser profile is in use — close other JARVIS instances "
                        "(or delete data/browser_profile) and try again."
                    )
                elif "executable doesn't exist" in msg or "chrome" in msg.lower():
                    self._start_err = (
                        "Chrome not found — install Google Chrome "
                        "from https://www.google.com/chrome"
                    )
                elif "playwright install" in msg.lower():
                    self._start_err = (
                        "Playwright driver missing — run: playwright install chrome"
                    )
                else:
                    self._start_err = f"Browser failed to start: {msg}"

    def stop(self) -> None:
        """Close Chrome. Safe to call even when not started."""
        with self._lock:
            for obj, method in [
                (self._page,    "close"),
                (self._context, "close"),
                (self._browser, "close"),
                (self._pw,      "stop"),
            ]:
                try:
                    if obj is not None:
                        getattr(obj, method)()
                except Exception:
                    pass
            self._pw = self._browser = self._context = self._page = None
            self._ready = False

    # ── Internal helpers ──────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def start_error(self) -> str:
        """Public read of the most recent start() failure message (empty if none)."""
        return self._start_err

    def _not_ready(self) -> dict | None:
        """Return _err if session is not ready after one auto-restart attempt, else None.

        Uses RLock so _recover() can re-enter while the caller already holds it.
        """
        if self._ready:
            return None
        # Auto-restart once — covers Chrome crash / external close
        self._recover()
        if self._ready:
            return None
        return _err(self._start_err or "Browser not started — call browser.start() first")

    def _recover(self) -> bool:
        """Attempt to restart after the browser was closed externally.
        Called from within the lock — RLock lets us re-enter safely.
        """
        self.stop()
        self.start()
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
