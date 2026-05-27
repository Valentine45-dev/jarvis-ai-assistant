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

This module was split from a single core/browser.py file (R2-17c) into the
``core/browser`` package. ``BrowserSession`` is composed from mixins — one per
responsibility group — but its public surface is unchanged:
    from core.browser import browser          # module-level singleton
    from core.browser import BrowserSession    # the class
"""

from __future__ import annotations

from core.browser.interaction import _InteractionMixin
from core.browser.picker import _PickerMixin
from core.browser.session import _SessionBase
from core.browser.tabs import _TabsMixin


class BrowserSession(_InteractionMixin, _PickerMixin, _TabsMixin, _SessionBase):
    """Persistent Chrome session. Behaviour identical to the pre-split class;
    methods live in the interaction / picker / tabs mixins and lifecycle in
    ``_SessionBase``. The mixins define disjoint method names, so MRO order is
    irrelevant for correctness — ``_SessionBase`` supplies ``__init__``.
    """
    pass


# Module-level singleton — imported by executor and main
browser = BrowserSession()

__all__ = ["BrowserSession", "browser"]
