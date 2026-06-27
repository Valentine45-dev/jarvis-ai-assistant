"""Navigation + interaction mixin (R2-17c split).

``_InteractionMixin`` — navigate / click / fill / read / extract / scroll and
their search-aware locator helpers. Composed into ``BrowserSession`` in
``core/browser/__init__.py``. Method bodies are unchanged from the former
monolithic ``core/browser.py``.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from config.settings import config
from core.browser.session import (
    _SEARCH_INPUT_SELECTORS,
    _SEARCH_SUBMIT_SELECTORS,
    _SUBTRY,
    _TIMEOUT,
)
from core.handlers.shared import _err, _ok, _redact_value, _tlog


def _reg_domain(host: str) -> str:
    """Registrable-ish domain (last two labels) for loose same-site comparison —
    so github.com and a www.github.com redirect compare equal, but an off-host
    redirect (e.g. an SSO domain) does not."""
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


class _InteractionMixin:
    # ── Phase 1: Navigation ───────────────────────────────────────────────────

    def _nav_timeout(self) -> int:
        """Per-navigation timeout (ms), config-tunable at call time (no restart).
        Shared by navigate / go_back / go_forward / refresh / hard_refresh. Locator
        ops (clicks) keep the shorter module-level _TIMEOUT."""
        try:
            return int(getattr(config, "browser_nav_timeout_ms", 30_000))
        except Exception:
            return 30_000

    def _salvage_after_timeout(self, url: str) -> dict | None:
        """After a navigation TIMEOUT, decide if the page actually loaded slowly.

        Returns _ok(...) ONLY when ALL hold: the navigation committed to the target
        host, the DOM is at least ``interactive``, and there's real content (a title
        or body text). Any check raising or uncertain → None, so the caller hard
        fails (conservative — the salvage is for "a beat too slow", not "something is
        on the right URL"). No HTTP status is available after a goto timeout, so a
        slow-but-rendered 4xx from the right host counts as loaded — an accepted,
        vanishingly-rare edge (a >30 s page that is also an error page)."""
        try:
            target = urlparse(url).hostname or ""
            current = urlparse(self._page.url).hostname or ""
            if not target or not current or _reg_domain(target) != _reg_domain(current):
                return None                      # not on the target host / stuck
            state = self._page.evaluate("document.readyState")
            if state not in ("interactive", "complete"):
                return None                      # DOM not usable yet
            title = (self._page.title() or "").strip()
            body = ""
            if not title:
                try:
                    body = (self._page.evaluate(
                        "document.body ? document.body.innerText : ''") or "").strip()
                except Exception:
                    body = ""
            if not title and not body:
                return None                      # committed but blank / hung
            label = title or "(no title)"
            _tlog(f"✓ loaded slowly (salvaged after timeout) — \"{label}\"")
            return _ok(f"Navigated to {url!r} (loaded slowly) — {label}")
        except Exception:
            return None                          # any doubt → fail (conservative)

    def navigate(self, url: str) -> dict:
        """Go to url and wait for DOM content to load (up to browser_nav_timeout_ms,
        default 30 s). On timeout, salvage a slow-but-loaded page (see
        _salvage_after_timeout) instead of blind-failing."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        _tlog(f"❯ navigate {url}")

        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=self._nav_timeout())
                title = self._page.title()
                _tlog(f"✓ loaded \"{title}\"")
                return _ok(f"Navigated to {url!r} — {title}")
            except Exception as exc:
                msg = str(exc)
                if "closed" in msg.lower():
                    self._ready = False
                    if self._recover():
                        try:
                            self._page.goto(url, wait_until="domcontentloaded", timeout=self._nav_timeout())
                            _tlog(f"✓ loaded \"{self._page.title()}\"")
                            return _ok(f"Navigated to {url!r} — {self._page.title()}")
                        except Exception as exc2:
                            _tlog(f"✗ {exc2}")
                            return _err(str(exc2))
                    _tlog("✗ browser session lost — Chrome was closed externally")
                    return _err("Browser session lost — Chrome was closed externally")
                if "timeout" in msg.lower():
                    # Don't blind-fail: the page may have loaded a beat too slowly.
                    salvaged = self._salvage_after_timeout(url)
                    if salvaged is not None:
                        return salvaged
                    secs = self._nav_timeout() // 1000
                    _tlog(f"✗ timed out (>{secs} s): {url}")
                    return _err(f"Page took too long to load (>{secs} s): {url}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def go_back(self) -> dict:
        """Go back one entry in the active tab's history."""
        _tlog("❯ go back")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                response = self._page.go_back(wait_until="domcontentloaded", timeout=self._nav_timeout())
                if response is None:
                    _tlog("✗ no previous page in history")
                    return _err("No previous page in this tab's history.")
                title = self._page.title()
                _tlog(f"✓ back to {title!r}")
                return _ok(f"Back to {title}")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower():
                    _tlog(f"✗ go_back timed out: {msg}")
                    return _err(f"go_back timed out: {msg}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def go_forward(self) -> dict:
        """Go forward one entry in the active tab's history."""
        _tlog("❯ go forward")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                response = self._page.go_forward(wait_until="domcontentloaded", timeout=self._nav_timeout())
                if response is None:
                    _tlog("✗ no forward page in history")
                    return _err("No forward page in this tab's history.")
                title = self._page.title()
                _tlog(f"✓ forward to {title!r}")
                return _ok(f"Forward to {title}")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower():
                    _tlog(f"✗ go_forward timed out: {msg}")
                    return _err(f"go_forward timed out: {msg}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def refresh(self) -> dict:
        """Reload the active page (cache allowed)."""
        _tlog("❯ refresh")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=self._nav_timeout())
                title = self._page.title()
                _tlog(f"✓ reloaded — {title!r}")
                return _ok(f"Reloaded — {title}")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower():
                    _tlog(f"✗ refresh timed out: {msg}")
                    return _err(f"refresh timed out: {msg}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def hard_refresh(self) -> dict:
        """Reload the active page bypassing the HTTP cache (Ctrl+Shift+R equivalent).

        Uses a CDP ``Page.reload`` with ``ignoreCache=true`` since Playwright's
        ``page.reload()`` does not bypass cache by default. Falls back to a normal
        reload if the CDP session can't be opened (non-Chromium browser, etc.).
        """
        _tlog("❯ hard refresh")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                try:
                    cdp = self._context.new_cdp_session(self._page)
                except Exception:
                    # CDP unavailable — fall back to a regular reload so the
                    # action at least does *something* useful.
                    self._page.reload(wait_until="domcontentloaded", timeout=self._nav_timeout())
                    title = self._page.title()
                    _tlog(f"✓ reloaded (fallback, cache not bypassed) — {title!r}")
                    return _ok(f"Reloaded (cache not bypassed — CDP unavailable) — {title}")
                try:
                    cdp.send("Page.reload", {"ignoreCache": True})
                finally:
                    try:
                        cdp.detach()
                    except Exception:
                        pass
                try:
                    self._page.wait_for_load_state("domcontentloaded", timeout=self._nav_timeout())
                except Exception:
                    # Don't fail the whole op just because load-state wait timed out;
                    # the reload was issued.
                    pass
                title = self._page.title()
                _tlog(f"✓ reloaded (cache bypassed) — {title!r}")
                return _ok(f"Reloaded (cache bypassed) — {title}")
            except Exception as exc:
                _tlog(f"✗ {exc}")
                return _err(str(exc))

    # ── Phase 2: Interaction ──────────────────────────────────────────────────

    @staticmethod
    def _search_submit_selector_chain(primary: str) -> list[str]:
        """Uniques in order: primary, id-variants, then common search-button patterns."""
        p = (primary or "").strip()
        seen: set[str] = set()
        out: list[str] = []
        for s in (p, *_InteractionMixin._css_id_variants(p), *_SEARCH_SUBMIT_SELECTORS):
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

    def _fill_locator(self, loc, value: str) -> None:
        """Click, clear, and type through Playwright so SPA input handlers fire."""
        loc.click(timeout=_TIMEOUT)
        loc.press("Control+a")
        loc.press("Delete")
        loc.press_sequentially(value, delay=50)

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
        click_label = selector or text or (f"({x},{y})" if x is not None and y is not None else "")
        _tlog(f"❯ click {click_label!r}")

        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
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
                            _tlog("✓ clicked")
                            return r

                    if searchish:
                        r = self._try_search_role_buttons()
                        if r:
                            _tlog("✓ clicked")
                            return r
                        r = self._try_submit_search_by_enter()
                        if r:
                            _tlog("✓ clicked")
                            return r

                    if (text or "").strip():
                        tr = self._click_by_visible_text(text)
                        if tr.get("success"):
                            _tlog("✓ clicked")
                            return tr

                    _tlog(f"✗ element not found: {selector!r}")
                    return _err(f"Element not found: {selector!r}")
                if text:
                    tr = self._click_by_visible_text(text)
                    _tlog("✓ clicked" if tr.get("success") else f"✗ {tr.get('error') or 'not found'}")
                    return tr
                if x is not None and y is not None:
                    self._page.mouse.click(x, y)
                    _tlog("✓ clicked")
                    return _ok(f"Clicked at ({x}, {y})")
                _tlog("✗ provide selector, text, or (x, y) coordinates")
                return _err("Provide selector, text, or (x, y) coordinates")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    target = selector or text or f"({x},{y})"
                    _tlog(f"✗ element not found: {target!r}")
                    return _err(f"Element not found: {target!r}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def fill_form(self, fields: dict) -> dict:
        """Fill form fields. Each key is tried as CSS selector → label → placeholder
        → well-known search selectors.

        Uses click + Ctrl+A + Delete + press_sequentially so SPA event handlers
        (YouTube, React, etc.) fire on every keystroke rather than a silent value set.
        """
        if isinstance(fields, dict) and len(fields) == 1:
            _k, _v = next(iter(fields.items()))
            _tlog(f"❯ fill {_k!r} = {_redact_value(_k, _v)}")
        else:
            _tlog(f"❯ fill {len(fields) if isinstance(fields, dict) else 0} field(s)")

        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
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
                    for sel in _SEARCH_INPUT_SELECTORS:
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
                    self._fill_locator(loc, value)
                    filled.append(key)
                except Exception as exc:
                    errors.append(f"{key} ({exc})")

            if errors:
                _tlog(f"✗ could not fill: {', '.join(errors)}")
                return _err(f"Could not fill: {', '.join(errors)}")
            _tlog("✓ filled")
            return _ok(f"Filled {len(filled)} field(s): {', '.join(filled)}")

    def read_page(self) -> dict:
        """Read tab metadata plus visible page text: document title, URL, then body (capped)."""
        _PAGE_CAP = 4_000
        _tlog("❯ read_page")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
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
                    _tlog(f"✓ \"{title or '(no title)'}\" — 0 chars extracted")
                    return _ok(header + "(no visible text in main/article/body — try navigating or use read_screen.)")

                truncated = len(text) > _PAGE_CAP
                snippet = text[:_PAGE_CAP]
                if truncated:
                    snippet += f"\n\n[... truncated — showing {_PAGE_CAP} of {len(text)} chars]"
                _tlog(f"✓ \"{title or '(no title)'}\" — {len(text)} chars extracted")
                return _ok(header + snippet)
            except Exception as exc:
                _tlog(f"✗ {exc}")
                return _err(str(exc))

    def extract_content(self, selector: str = "") -> dict:
        """Return inner text of the first element matching selector."""
        if not selector:
            _tlog("✗ extract: no selector provided")
            return _err("No selector provided")
        _tlog(f"❯ extract {selector!r}")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                text = self._page.locator(selector).first.inner_text(timeout=_TIMEOUT)
                clipped = text.strip()[:2000]
                _tlog(f"✓ {len(clipped)} chars extracted")
                return _ok(clipped)
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    _tlog(f"✗ element not found: {selector!r}")
                    return _err(f"Element not found: {selector!r}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    def scroll(self, direction: str = "down", amount: int = 3) -> dict:
        """Scroll the active page. ``amount`` = scroll ticks (~300 px each).

        Matches the typical mouse-wheel feel — `amount: 3` ≈ one viewport on
        a 1080p screen. Clamped to [1, 50] so a bad model emit can't scroll
        forever."""
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"❯ scroll {direction} {amount}")
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            dir_norm = (direction or "down").strip().lower()
            if dir_norm not in ("up", "down"):
                _tlog(f"❯ scroll {direction} {amount}")
                _tlog(f"✗ invalid direction: {direction!r}")
                return _err(f"Invalid direction: {direction!r} (use 'up' or 'down')")
            try:
                n = max(1, min(int(amount), 50))
            except (TypeError, ValueError):
                n = 3
            delta_y = n * 300 * (1 if dir_norm == "down" else -1)
            _tlog(f"❯ scroll {dir_norm} {n}")

            def _do() -> dict:
                self._page.mouse.wheel(0, delta_y)
                _tlog(f"✓ scrolled ~{abs(delta_y)}px")
                return _ok(f"Scrolled {dir_norm} {n} tick{'s' if n != 1 else ''}.")

            result = self._with_recovery("scroll", _do)
            if not result.get("success"):
                _tlog(f"✗ {result.get('error') or 'scroll failed'}")
            return result
