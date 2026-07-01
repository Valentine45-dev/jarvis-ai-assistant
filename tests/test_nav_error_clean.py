"""P6 — nav-error cosmetic: the primary SYS_LOG line is humanized, not raw Playwright.

Bug (sweep find): navigating to a dead URL surfaced the RAW Playwright error on the
primary line — 'Page.goto: net::ERR_NAME_NOT_RESOLVED ... Call log: - navigating to ...'
— while the narration line was already clean. Fix: _clean_nav_error strips the
'Call log:' tail + 'Page.goto:' prefix and maps the net:: code to a human message.
"""

from __future__ import annotations

import core.browser.interaction as bi

_RAW_DNS = (
    "Page.goto: net::ERR_NAME_NOT_RESOLVED at https://help.thisdoesnotexist1234.com/\n"
    'Call log:\n  - navigating to "https://help.thisdoesnotexist1234.com/", waiting until '
    '"domcontentloaded"\n'
)


def test_dns_error_is_humanized_and_tail_stripped():
    out = bi._clean_nav_error(_RAW_DNS, "https://help.thisdoesnotexist1234.com")
    assert "help.thisdoesnotexist1234.com" in out
    assert "couldn't resolve" in out.lower()
    # all the raw developer noise is gone
    assert "Call log" not in out
    assert "Page.goto" not in out
    assert "net::" not in out


def test_connection_refused():
    out = bi._clean_nav_error(
        "Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:9/ Call log: - x",
        "http://localhost:9",
    )
    assert "refused" in out.lower()
    assert "Call log" not in out


def test_cert_error():
    out = bi._clean_nav_error(
        "net::ERR_CERT_DATE_INVALID at https://expired.example Call log:",
        "https://expired.example",
    )
    assert "certificate" in out.lower()


def test_generic_fallback_strips_noise():
    out = bi._clean_nav_error(
        "Page.goto: some weird failure\nCall log:\n - navigating", "https://x.example",
    )
    assert "Call log" not in out
    assert "Page.goto" not in out
    assert "x.example" in out
