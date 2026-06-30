"""Fix: close_all_engines — the executor enumerates the live engine registry.

The brain used to GUESS which engines were open for "close the two browsers you
just opened" (Chrome+Firefox live → it emitted [close firefox, close edge] and
failed on the guessed edge). The fix routes plural/all browser-close requests to
close_all_engines, which closes whatever is actually in self._sessions — no
naming, no counting, immune to a brain miscount.

These drive _SessionBase.close_all_engines() directly with stubbed engine
sessions (page/context = None → teardown no-ops; _pw = None → no Playwright), and
verify the handler routes to it WITHOUT first auto-starting a browser.
"""

from __future__ import annotations

import types

from core.browser.session import _SessionBase, _EngineSession


def _session_with(*engines: str) -> _SessionBase:
    s = _SessionBase()
    for eng in engines:
        sess = _EngineSession(eng)
        sess.ready = True           # page/context stay None → close() loop no-ops
        s._sessions[eng] = sess
    s._active = engines[0] if engines else ""
    return s


def test_close_all_engines_closes_every_open_engine():
    s = _session_with("chrome", "firefox")
    out = s.close_all_engines()
    assert out["success"] is True
    # names both engines it closed
    assert "chrome" in out["output"] and "firefox" in out["output"]
    # registry emptied, nothing left active
    assert s._sessions == {}
    assert s._active == ""


def test_close_all_engines_single_engine():
    s = _session_with("chrome")
    out = s.close_all_engines()
    assert out["success"] is True
    assert "chrome" in out["output"] and " and " not in out["output"]
    assert s._sessions == {}


def test_close_all_engines_no_op_when_none_open():
    s = _session_with()                      # nothing open
    out = s.close_all_engines()
    # Friendly no-op — success, NOT an error/red rail.
    assert out["success"] is True
    assert "No browsers were open" in out["output"]


def test_handler_routes_close_all_without_autostart(monkeypatch):
    import core.handlers.browser_handler as bh

    called: dict[str, bool] = {}
    fake = types.SimpleNamespace(
        close_all_engines=lambda: (called.__setitem__("closed_all", True),
                                   {"success": True, "output": "Closed chrome and firefox.", "error": ""})[1],
        # if the route were misplaced (after the auto-start guard) these would fire:
        is_ready=False,
        start=lambda: called.__setitem__("started", True),
    )
    monkeypatch.setattr("core.browser.browser", fake)

    out = bh._handle_browser_automation("close_all_engines", {})
    assert called.get("closed_all") is True
    assert called.get("started") is None, "close must NOT auto-start a browser first"
    assert out["success"] and "chrome" in out["output"]
