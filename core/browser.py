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
Tabs:                       browser.new_tab(url)
              browser.close_tab()  # or close_tab(match="…") / url_contains="…" to target a tab

All public methods return {success: bool, output: str, error: str}.
"""

from __future__ import annotations

import re
import threading

_TIMEOUT = 15_000   # ms — max wait per page/locator operation
_SUBTRY    = 4_000   # ms per fallback locator attempt


def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}

def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


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

    @staticmethod
    def _search_submit_selector_chain(primary: str) -> list[str]:
        """Uniques in order: primary, id-variants, then common search-button patterns."""
        p = (primary or "").strip()
        seen: set[str] = set()
        out: list[str] = []
        for s in (p, *BrowserSession._css_id_variants(p), *_SEARCH_SUBMIT_SELECTORS):
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    @staticmethod
    def _css_id_variants(selector: str) -> list[str]:
        """E.g. ``button#search-icon-legacy`` → add ``#search-icon-legacy``."""
        m = re.search(r"#[A-Za-z0-9_-]+", selector)
        if not m:
            return []
        i = m.group(0)
        if not selector.lstrip().lower().startswith("button") and f"button{i}" not in selector:
            return [f"button{i}", i]
        return [i]

    def _is_search_submission_intent(
        self, selector: str = "", text: str = "", url: str = ""
    ) -> bool:
        s = f"{selector} {text}".lower()
        if any(k in s for k in ("search", "searchbox", "query", "icon-legacy", "magnif")):
            return True
        u = (url or self._page.url or "").lower()
        return any(d in u for d in ("youtube", "google.", "bing.com", "duckduckgo"))

    def _try_click_locator(self, how: str, loc) -> dict | None:
        try:
            if loc.count() == 0:
                return None
            first = loc.first
            if not first.is_visible(timeout=1_200):
                return None
            first.click(timeout=_SUBTRY)
            return _ok(f"Clicked {how}")
        except Exception:
            return None

    def _try_search_role_buttons(self) -> dict | None:
        """get_by_role + accessible name — survives YouTube changing raw #ids."""
        for pattern in (
            re.compile(r"search", re.I),
            re.compile(r"^go\s+to\s+search$", re.I),
        ):
            try:
                loc = self._page.get_by_role("button", name=pattern)
                n = min(loc.count(), 8)
                for i in range(n):
                    el = loc.nth(i)
                    try:
                        if el.is_visible(timeout=800):
                            el.click(timeout=_SUBTRY)
                            return _ok("Clicked button (name pattern match for search/submit)")
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    def _try_submit_search_by_enter(self) -> dict | None:
        """Focus a visible search field and press Enter (YouTube, Google, etc. when the icon is hidden)."""
        for sel in _SEARCH_INPUT_SELECTORS:
            try:
                loc = self._page.locator(sel)
                if loc.count() == 0:
                    continue
                first = loc.first
                if not first.is_visible(timeout=1_500):
                    continue
                first.click(timeout=_SUBTRY)
                self._page.keyboard.press("Enter")
                return _ok("Submitted search (Enter on search field)")
            except Exception:
                continue
        return None

    def _click_by_visible_text(self, text: str) -> dict:
        """Text / role / search fallbacks; used for plain-text clicks and after selector miss."""
        _TRY = 5_000
        strategies = [
            lambda: self._page.get_by_role("link", name=text, exact=False).first.click(
                timeout=_TRY
            ),
            lambda: self._page.get_by_role("button", name=text, exact=False).first.click(
                timeout=_TRY
            ),
            lambda: self._page.locator(f"text={text}").first.click(timeout=_TRY),
            lambda: self._page.get_by_text(text, exact=False).first.click(timeout=_TRY),
        ]
        for strategy in strategies:
            try:
                strategy()
                return _ok(f"Clicked element with text: {text!r}")
            except Exception:
                continue
        tlow = (text or "").lower()
        if "search" in tlow and self._is_search_submission_intent(text=text):
            r = self._try_search_role_buttons()
            if r:
                return r
            r = self._try_submit_search_by_enter()
            if r:
                return r
        return _err(f"Element not found: {text!r}")

    def click_element(self, selector: str = "", text: str = "",
                      x: int | None = None, y: int | None = None) -> dict:
        """Click by CSS selector, visible text, or pixel coordinates.
        Priority: selector (with search fallbacks) → optional text if selector fails
        (when both are given) → text-only. Then (x, y) only when no text/selector.
        """
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                if selector:
                    searchish = self._is_search_submission_intent(
                        selector, text, self._page.url
                    )
                    chain = self._search_submit_selector_chain(selector) if searchish else [selector]
                    if not searchish:
                        chain = [selector] + self._css_id_variants(selector)

                    for s in list(dict.fromkeys(chain)):
                        r = self._try_click_locator(f"selector {s!r}", self._page.locator(s))
                        if r:
                            return r

                    if searchish:
                        r = self._try_search_role_buttons()
                        if r:
                            return r
                        r = self._try_submit_search_by_enter()
                        if r:
                            return r

                    if (text or "").strip():
                        tr = self._click_by_visible_text(text)
                        if tr.get("success"):
                            return tr

                    return _err(f"Element not found: {selector!r}")
                if text:
                    return self._click_by_visible_text(text)
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
        # Well-known search bar selectors (kept in sync with click Enter fallback)
        _search_sel_extra = [
            "#search-input",
            ".search-input",
        ]
        _all_search = list(
            dict.fromkeys([* _SEARCH_INPUT_SELECTORS, * _search_sel_extra])
        )

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
                    for sel in _all_search:
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

    @staticmethod
    def _safe_title(page) -> str:
        try:
            return (page.title() or "").strip()
        except Exception:
            return ""

    def _pages_with_url_title(self) -> list[tuple[object, str, str]]:
        rows: list[tuple[object, str, str]] = []
        for p in self._context.pages:
            u = p.url or ""
            t = self._safe_title(p)
            rows.append((p, u, t))
        return rows

    def _list_tabs_brief(self) -> str:
        """Short summary for 'no match' error messages (max 5 tabs)."""
        parts: list[str] = []
        for p, u, t in self._pages_with_url_title()[:5]:
            host = u.split("://", 1)[-1].split("/", 1)[0][:40] if u else "?"
            tail = t[:50] + ("…" if len(t) > 50 else "")
            parts.append(f"{host} — {tail or '(no title)'}")
        return "; ".join(parts) if parts else "(none)"

    @staticmethod
    def _match_tokens(m: str) -> list[str]:
        return [w for w in re.split(r"[^\w]+", m.lower()) if len(w) >= 2]

    @staticmethod
    def _score_page_for_keywords(u: str, t: str, tokens: list[str]) -> int:
        """URL matches rank above title-only (avoids wrong tab when one title says ' - YouTube')."""
        u_l, t_l = (u or "").lower(), (t or "").lower()
        s = 0
        for tok in tokens:
            if tok in u_l:
                s += 10
            elif tok in t_l:
                s += 5
        return s

    def _find_page_to_close(
        self,
        *,
        title_contains: str,
        url_contains: str,
        match: str,
    ) -> tuple[object | None, str]:
        """
        Return (Page | None, reason).
        *None* + reason only when a filter was given but no tab matched.
        """
        rows = self._pages_with_url_title()
        tc = (title_contains or "").strip()
        uc = (url_contains or "").strip()
        m = (match or "").strip()

        if not tc and not uc and not m:
            return self._page, "active"

        if uc or tc:
            uc_l, tc_l = uc.lower(), tc.lower()
            for p, u, t in rows:
                ok_u = (not uc) or (uc_l in (u or "").lower())
                ok_t = (not tc) or (tc_l in (t or "").lower())
                if uc and tc:
                    if ok_u and ok_t:
                        return p, "url+title"
                elif uc and ok_u:
                    return p, "url"
                elif tc and ok_t:
                    return p, "title"
            return None, "no_explicit_match"

        tokens = self._match_tokens(m)
        if not tokens:
            return None, "no_tokens"

        best: object | None = None
        best_s = -1
        for p, u, t in rows:
            s = self._score_page_for_keywords(u, t, tokens)
            if s > best_s:
                best_s = s
                best = p
        if best is not None and best_s > 0:
            return best, f"match_score={best_s}"
        return None, "no_keyword_match"

    def close_tab(
        self,
        *,
        title_contains: str = "",
        url_contains: str = "",
        match: str = "",
    ) -> dict:
        """Close a tab. With no *match* / *url_contains* / *title_contains*, closes the active tab.

        Otherwise find the first tab whose URL/title matches (so a background tab
        can be closed without making it active first). ``match`` is a free-text phrase;
        substrings are tokenised and scored (URL match beats title match).
        """
        with self._lock:
            guard = self._not_ready()
            if guard:
                return guard
            try:
                target, _reason = self._find_page_to_close(
                    title_contains=title_contains,
                    url_contains=url_contains,
                    match=match,
                )
                if target is None and (title_contains or url_contains or match):
                    return _err(
                        f"No open tab matched that description. Open tabs: {self._list_tabs_brief()}"
                    )
                if target is None:
                    target = self._page

                was_active = target == self._page
                target.close()
                remaining = list(self._context.pages)
                if not remaining:
                    self._page = self._context.new_page()
                    return _ok("All tabs were closed; opened a new blank tab.")

                if (not was_active) and any(self._page is p for p in remaining):
                    return _ok(
                        f"Tab closed (matched request) — active tab: {self._safe_title(self._page)!r}"
                    )
                self._page = remaining[-1]
                return _ok(
                    f"Tab closed — active tab: {self._safe_title(self._page)!r}"
                )
            except Exception as exc:
                return _err(str(exc))


# Module-level singleton — imported by executor and main
browser = BrowserSession()
