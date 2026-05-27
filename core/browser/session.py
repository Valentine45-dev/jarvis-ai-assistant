"""Browser session core: shared constants + lifecycle (R2-17c split).

Part of the ``core/browser`` package. Houses the module-level constants and
the ``_SessionBase`` lifecycle class. The sibling mixins (interaction, picker,
tabs) import constants *from* this module; this module imports none of them,
so there is no circular import.
"""

from __future__ import annotations

import threading

from core.handlers.shared import _err

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
                self._pw      = sync_playwright().start()
                self._browser = self._pw.chromium.launch(
                    channel="chrome",
                    headless=False,
                    args=["--force-renderer-accessibility"],
                )
                self._context = self._browser.new_context()
                self._page    = self._context.new_page()
                self._ready     = True
                self._start_err = ""
            except Exception as exc:
                self._ready = False
                msg = str(exc)
                if "executable doesn't exist" in msg or "chrome" in msg.lower():
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
