"""Screenshots + tab management mixin (R2-17c split).

``_TabsMixin`` — full-page / element screenshots and new/switch/close tab
operations plus their scoring helpers. Composed into ``BrowserSession`` in
``core/browser/__init__.py``. Method bodies are unchanged from the former
monolithic ``core/browser.py``.
"""

from __future__ import annotations

import re

from core.browser.session import _TIMEOUT
from core.handlers.shared import _err, _ok, _tlog


class _TabsMixin:
    # ── Phase 2: Screenshots ──────────────────────────────────────────────────

    def screenshot_page(self, path: str | None = None) -> dict:
        """Full-page screenshot. Saves to Desktop if no path given."""
        from pathlib import Path
        _tlog("❯ browser screenshot")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                save_path = path or str(Path.home() / "Desktop" / "jarvis_browser_screenshot.png")
                self._page.screenshot(path=save_path, full_page=True)
                _tlog(f"✓ saved → {Path(save_path).name}")
                return _ok(f"Screenshot saved: {save_path}")
            except Exception as exc:
                _tlog(f"✗ {exc}")
                return _err(str(exc))

    def screenshot_element(self, selector: str = "", path: str | None = None) -> dict:
        """Screenshot a specific element matching selector."""
        from pathlib import Path
        if not selector:
            _tlog("✗ browser screenshot: no selector provided")
            return _err("No selector provided")
        _tlog(f"❯ browser screenshot {selector!r}")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                save_path = path or str(Path.home() / "Desktop" / "jarvis_element_screenshot.png")
                self._page.locator(selector).first.screenshot(path=save_path, timeout=_TIMEOUT)
                _tlog(f"✓ saved → {Path(save_path).name}")
                return _ok(f"Element screenshot saved: {save_path}")
            except Exception as exc:
                msg = str(exc)
                if "timeout" in msg.lower() or type(exc).__name__ == "TimeoutError":
                    _tlog(f"✗ element not found: {selector!r}")
                    return _err(f"Element not found: {selector!r}")
                _tlog(f"✗ {msg}")
                return _err(msg)

    # ── Phase 2: Tab management ───────────────────────────────────────────────

    def new_tab(self, url: str = "") -> dict:
        """Open a new tab and optionally navigate to url. Makes the new tab active."""
        _tlog(f"❯ new tab → {url or 'blank'}")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                self._page = self._context.new_page()
                if url:
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT)
                    title = self._page.title()
                    _tlog(f"✓ loaded \"{title}\"")
                    return _ok(f"New tab → {url!r} — {title}")
                _tlog("✓ loaded \"(blank)\"")
                return _ok("New blank tab opened")
            except Exception as exc:
                _tlog(f"✗ {exc}")
                return _err(str(exc))

    def switch_tab(self, target: str) -> dict:
        """Bring an existing tab to the front by URL or title keyword.

        Tokenises ``target`` and scores every open tab the same way close_tab
        does (URL substring beats title substring), so commands like
        *"switch to youtube tab"* land on the YouTube page rather than a
        random page whose ``<title>`` happens to mention YouTube. Updates
        ``self._page`` so subsequent actions (read_page, click, fill, …)
        operate on the now-active tab.

        Returns ``_ok`` with the matched title; ``_err`` with a brief tab
        list when no tab matches the keyword.
        """
        target = (target or "").strip()
        _tlog(f"❯ switch tab → {target!r}")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard

            if not target:
                _tlog("✗ no target keyword provided")
                return _err("No target keyword provided for switch_tab.")

            tokens = self._match_tokens(target)
            if not tokens:
                _tlog("✗ target had no usable keywords")
                return _err(
                    f"Couldn't parse {target!r} into a search keyword."
                )

            best_page = None
            best_score = 0
            best_title = ""
            for p, u, t in self._pages_with_url_title():
                score = self._score_page_for_keywords(u, t, tokens)
                if score > best_score:
                    best_score = score
                    best_page = p
                    best_title = t or u or "(untitled)"

            if best_page is None:
                _tlog("✗ no open tab matched")
                return _err(
                    f"No open tab matches {target!r}. Open tabs: {self._list_tabs_brief()}"
                )

            try:
                best_page.bring_to_front()
            except Exception as exc:
                _tlog(f"✗ bring_to_front failed: {exc}")
                return _err(str(exc))

            self._page = best_page
            _tlog(f"✓ switched → {best_title!r}")
            return _ok(f"Switched to {best_title!r}")

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
        _filter_label = url_contains or title_contains or match or "active"
        _tlog(f"❯ close tab ({_filter_label})")
        with self._lock:
            guard = self._not_ready()
            if guard:
                _tlog(f"✗ {guard.get('error') or 'browser not ready'}")
                return guard
            try:
                target, _reason = self._find_page_to_close(
                    title_contains=title_contains,
                    url_contains=url_contains,
                    match=match,
                )
                if target is None and (title_contains or url_contains or match):
                    _tlog("✗ no open tab matched that description")
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
                    _tlog("✓ closed (opened new blank tab)")
                    return _ok("All tabs were closed; opened a new blank tab.")

                if (not was_active) and any(self._page is p for p in remaining):
                    _tlog("✓ closed")
                    return _ok(
                        f"Tab closed (matched request) — active tab: {self._safe_title(self._page)!r}"
                    )
                self._page = remaining[-1]
                _tlog("✓ closed")
                return _ok(
                    f"Tab closed — active tab: {self._safe_title(self._page)!r}"
                )
            except Exception as exc:
                _tlog(f"✗ {exc}")
                return _err(str(exc))
