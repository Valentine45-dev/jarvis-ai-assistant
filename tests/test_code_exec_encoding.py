"""P4 — code_execution raw stdout is UTF-8, no mojibake.

Bug (sweep find): 'weather tomorrow?' routed to code_execution (Python via urllib),
and the raw stdout showed '16.36�C' — the degree sign and an arrow rendered as '�'.
The interpreted narration line above it was fine ('16.4°C') because it's produced
in-process; only the child's raw stdout mis-rendered. Cause: _stream_execute DECODES
the child's stdout as UTF-8, but a piped Python child on Windows ENCODES stdout in
the locale codepage (cp1252), so '°' (0xB0) is invalid UTF-8 → '�'. Fix: force the
child into UTF-8 I/O (PYTHONIOENCODING/PYTHONUTF8) so its bytes match our decode.
"""

from __future__ import annotations

import sys

import core.handlers.code_exec as ce
from core.signals import signals


class _FakeSig:
    def emit(self, *a, **k):
        pass


def test_stream_execute_preserves_utf8_non_ascii(monkeypatch):
    monkeypatch.setattr(signals, "terminal_line_ready", _FakeSig())
    monkeypatch.setattr(signals, "terminal_done", _FakeSig())
    # the child GENERATES the non-ASCII chars internally (via \u escapes) and prints
    # them — with the fix it emits UTF-8, which our UTF-8 decode round-trips cleanly.
    out, code, _ms = ce._stream_execute(
        [sys.executable, "-c", "print('16.4\\u00b0C \\u2192 warm')"],
        cwd=None, timeout=15,
    )
    assert code == 0
    assert "°C" in out          # ° survived
    assert "→" in out           # → survived
    assert "�" not in out       # no replacement char (mojibake)
