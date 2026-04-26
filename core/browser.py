"""
Persistent Playwright Chrome session.
Uses playwright.sync_api — no asyncio, compatible with PyQt5's event loop.

Lifecycle:
  browser.start()       — launch Chrome; call at JARVIS startup
  browser.stop()        — close Chrome; call at shutdown / closeEvent

Navigation:   browser.navigate(url)
Interaction:  browser.click_element(selector, text, x, y)
              browser.fill_form(fields)
              browser.read_page()
              browser.extract_content(selector)
Screenshots:  browser.screenshot_page(path)
              browser.screenshot_element(selector, path)
Tabs:         browser.new_tab(url)
              browser.close_tab()

All public methods return {success: bool, output: str, error: str}.
"""

from __future__ import annotations

import threading

_TIMEOUT = 15_000   # ms — max wait per page/locator operation


def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}

def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


class BrowserSession:
    def __init__(self) -> None:
        # RLock so _recover() can re-enter while the caller already holds the lock
        self._lock = threading.RLock()
        self._pw        = None  # playwright context manager handle
        self._browser   = None
        self._context   = None
        self._page      = None
        self._ready     = False
        self._start_err = ""

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

    def _not_ready(self) -> dict | None:
        """Return _err if session is not ready, else None."""
        if not self._ready:
            return _err(self._start_err or "Browser not started — call browser.start() first")
        return None

    def _recover(self) -> bool:
        """Attempt to restart after the browser was closed externally.
        Called from within the lock — RLock lets us re-enter safely.
        """
        self.stop()
        self.start()
        return self._ready

    # ── Phase 1: Navigation ───────────────────────────────────────────────────

    def navigate(self, url: str) -> dict:
        """Go to url and wait for DOM content to load (max 15 s)."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT)
                title = self._page.title()
                return _ok(f"Navigated to {url!r} — {title}")
            except Exception as exc:
                msg = str(exc)
                if "closed" in msg.lower():
                    self._ready = False
                    if self._recover():
                        try:
                            self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT)
                            return _ok(f"Navigated to {url!r} — {self._page.title()}")
                        except Exception as exc2:
                            return _err(str(exc2))
                    return _err("Browser session lost — Chrome was closed externally")
                if "timeout" in msg.lower():
                    return _err(f"Page took too long to load (>15 s): {url}")
                return _err(msg)

    # ── Phase 2: Interaction ──────────────────────────────────────────────────

    def click_element(self, selector: str = "", text: str = "",
                      x: int | None = None, y: int | None = None) -> dict:
        """Click by CSS selector, visible text, or pixel coordinates.
        Priority: selector → text → (x, y).
        """
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                if selector:
                    self._page.locator(selector).first.click(timeout=_TIMEOUT)
                    return _ok(f"Clicked selector: {selector!r}")
                if text:
                    _TRY = 5_000   # per-strategy timeout so failures are fast
                    strategies = [
                        lambda: self._page.get_by_role("link",   name=text, exact=False).first.click(timeout=_TRY),
                        lambda: self._page.get_by_role("button", name=text, exact=False).first.click(timeout=_TRY),
                        lambda: self._page.locator(f"text={text}").first.click(timeout=_TRY),
                        lambda: self._page.get_by_text(text, exact=False).first.click(timeout=_TRY),
                    ]
                    for strategy in strategies:
                        try:
                            strategy()
                            return _ok(f"Clicked element with text: {text!r}")
                        except Exception:
                            continue
                    return _err(f"Element not found: {text!r}")
                if x is not None and y is not None:
                    self._page.mouse.click(x, y)
                    return _ok(f"Clicked at ({x}, {y})")
                return _err("Provide selector, text, or (x, y) coordinates")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    target = selector or text or f"({x},{y})"
                    return _err(f"Element not found: {target!r}")
                return _err(msg)

    def fill_form(self, fields: dict) -> dict:
        """Fill form fields. Each key is tried as CSS selector → label → placeholder
        → well-known search selectors.

        Uses click + Ctrl+A + Delete + press_sequentially so SPA event handlers
        (YouTube, React, etc.) fire on every keystroke rather than a silent value set.
        """
        # Well-known search bar selectors tried when the key hints at a search field
        _SEARCH_SELECTORS = [
            "input#search",                     # YouTube
            "input[name='search_query']",       # YouTube
            "ytd-searchbox input",              # YouTube shadow DOM
            "input[name='q']",                  # Google, Bing
            "textarea[name='q']",               # Google
            "[aria-label*='Search']",           # ARIA generic
            "[aria-label*='search']",
            "input[type='search']",             # HTML5 generic
            "[role='searchbox']",               # WAI-ARIA
            "#search-input",                    # Common IDs
            ".search-input",
            "input[placeholder*='earch']",      # Fuzzy placeholder
        ]

        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            filled, errors = [], []
            for key, value in fields.items():
                value = str(value)
                loc   = None

                # 1. CSS selector
                try:
                    candidate = self._page.locator(key)
                    if candidate.count() > 0 and candidate.first.is_visible(timeout=2_000):
                        loc = candidate.first
                except Exception:
                    pass

                # 2. Label text
                if loc is None:
                    try:
                        candidate = self._page.get_by_label(key, exact=False)
                        if candidate.count() > 0:
                            loc = candidate.first
                    except Exception:
                        pass

                # 3. Placeholder text
                if loc is None:
                    try:
                        candidate = self._page.get_by_placeholder(key, exact=False)
                        if candidate.count() > 0:
                            loc = candidate.first
                    except Exception:
                        pass

                # 4. Well-known search selectors (when key implies a search bar)
                if loc is None and any(
                    w in key.lower() for w in ("search", "query", "find", "look")
                ):
                    for sel in _SEARCH_SELECTORS:
                        try:
                            candidate = self._page.locator(sel)
                            if candidate.count() > 0 and candidate.first.is_visible(timeout=500):
                                loc = candidate.first
                                break
                        except Exception:
                            continue

                # 5. Last resort: any visible text input on the page
                if loc is None:
                    try:
                        candidate = self._page.locator("input:visible, textarea:visible")
                        if candidate.count() > 0:
                            loc = candidate.first
                    except Exception:
                        pass

                if loc is None:
                    errors.append(key)
                    continue

                # Click → select all → delete → type keystroke-by-keystroke
                try:
                    loc.click(timeout=_TIMEOUT)
                    loc.press("Control+a")
                    loc.press("Delete")
                    loc.press_sequentially(value, delay=50)
                    filled.append(key)
                except Exception as exc:
                    errors.append(f"{key} ({exc})")

            if errors:
                return _err(f"Could not fill: {', '.join(errors)}")
            return _ok(f"Filled {len(filled)} field(s): {', '.join(filled)}")

    def read_page(self) -> dict:
        """Read tab metadata plus visible page text: document title, URL, then body (capped)."""
        _PAGE_CAP = 4_000
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                url = self._page.url
                title = (self._page.title() or "").strip()
                header = (
                    "--- Tab ---\n"
                    f"Document title: {title or '(none)'}\n"
                    f"URL: {url}\n"
                    "\n--- Page content ---\n"
                )

                text = ""
                for sel in ("main", "article", '[role="main"]', "body"):
                    try:
                        loc = self._page.locator(sel)
                        if loc.count() > 0:
                            candidate = loc.first.inner_text(timeout=5_000).strip()
                            if candidate:
                                text = candidate
                                break
                    except Exception:
                        continue

                if not text:
                    return _ok(header + "(no visible text in main/article/body — try navigating or use read_screen.)")

                truncated = len(text) > _PAGE_CAP
                snippet = text[:_PAGE_CAP]
                if truncated:
                    snippet += f"\n\n[... truncated — showing {_PAGE_CAP} of {len(text)} chars]"
                return _ok(header + snippet)
            except Exception as exc:
                return _err(str(exc))

    def extract_content(self, selector: str = "") -> dict:
        """Return inner text of the first element matching selector."""
        if not selector:
            return _err("No selector provided")
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                text = self._page.locator(selector).first.inner_text(timeout=_TIMEOUT)
                return _ok(text.strip()[:2000])
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    return _err(f"Element not found: {selector!r}")
                return _err(msg)

    # ── Phase 2: Screenshots ──────────────────────────────────────────────────

    def screenshot_page(self, path: str | None = None) -> dict:
        """Full-page screenshot. Saves to Desktop if no path given."""
        from pathlib import Path
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                save_path = path or str(Path.home() / "Desktop" / "jarvis_browser_screenshot.png")
                self._page.screenshot(path=save_path, full_page=True)
                return _ok(f"Screenshot saved: {save_path}")
            except Exception as exc:
                return _err(str(exc))

    def screenshot_element(self, selector: str = "", path: str | None = None) -> dict:
        """Screenshot a specific element matching selector."""
        from pathlib import Path
        if not selector:
            return _err("No selector provided")
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                save_path = path or str(Path.home() / "Desktop" / "jarvis_element_screenshot.png")
                self._page.locator(selector).first.screenshot(path=save_path, timeout=_TIMEOUT)
                return _ok(f"Element screenshot saved: {save_path}")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    return _err(f"Element not found: {selector!r}")
                return _err(msg)

    # ── Phase 2: Tab management ───────────────────────────────────────────────

    def new_tab(self, url: str = "") -> dict:
        """Open a new tab and optionally navigate to url. Makes the new tab active."""
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                self._page = self._context.new_page()
                if url:
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT)
                    return _ok(f"New tab → {url!r} — {self._page.title()}")
                return _ok("New blank tab opened")
            except Exception as exc:
                return _err(str(exc))

    def close_tab(self) -> dict:
        """Close the active tab. Switches to the previous tab, or opens blank if last."""
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                self._page.close()
                pages = self._context.pages
                if pages:
                    self._page = pages[-1]
                    return _ok(f"Tab closed — active tab: {self._page.title()!r}")
                # All tabs closed — keep session alive with a fresh blank page
                self._page = self._context.new_page()
                return _ok("Last tab closed — new blank tab opened")
            except Exception as exc:
                return _err(str(exc))


# Module-level singleton — imported by executor and main
browser = BrowserSession()
