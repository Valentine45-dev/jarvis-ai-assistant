"""Manual launch-smoke harness for the JarvisWindow split (R2-17a).

NOT a pytest test (no ``test_`` prefix → never auto-collected). pytest
deliberately never instantiates JarvisWindow, so the suite alone cannot
prove Qt signal/slot wiring or that virtual overrides (paintEvent etc.)
hosted on a mixin actually get dispatched by Qt. This harness does.

Run:  uv run python tests/smoke_window.py

It:
  1. builds a QApplication and instantiates the REAL JarvisWindow,
  2. instruments the four Qt virtual overrides (paintEvent, resizeEvent,
     closeEvent, nativeEvent) AT THE CLASS IN THE MRO THAT DEFINES THEM,
     so the report names whether a virtual is hosted by JarvisWindow or by
     a mixin, and counts how many times Qt actually invoked it,
  3. shows the window + pumps the event loop (fires paintEvent/resizeEvent),
  4. drives a few SAFE in-process interactions (view nav, state cycle,
     status toast) — no mic, no TTS, no network,
  5. closes the window (fires closeEvent) and prints a PASS/FAIL report.

Exit code 0 = all assertions held; 1 = something regressed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root on path when run as a script from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

import main as m


def _patch_virtual(name: str, counters: dict, hosts: dict) -> None:
    """Wrap the override `name` on the class in JarvisWindow's MRO that
    actually defines it, recording the host class name and a call count.

    Patching at the defining class (not on JarvisWindow unconditionally)
    is the whole point: post-split, the host will be a mixin, and a non-zero
    count proves Qt dispatched the mixin-hosted virtual.
    """
    for cls in m.JarvisWindow.__mro__:
        if name in cls.__dict__:
            hosts[name] = cls.__name__
            orig = cls.__dict__[name]

            def wrapped(self, *a, __orig=orig, __n=name, **kw):
                counters[__n] = counters.get(__n, 0) + 1
                return __orig(self, *a, **kw)

            setattr(cls, name, wrapped)
            return
    hosts[name] = "<undefined>"


def main() -> int:
    counters: dict[str, int] = {}
    hosts: dict[str, str] = {}
    for v in ("paintEvent", "resizeEvent", "closeEvent", "nativeEvent"):
        _patch_virtual(v, counters, hosts)

    app = QApplication(sys.argv)

    failures: list[str] = []
    try:
        w = m.JarvisWindow()
        w.showMaximized()

        # Pump the loop so paint/resize actually dispatch.
        for _ in range(30):
            app.processEvents()

        # ── Safe in-process interactions (no mic/TTS/network) ──────────────
        # View navigation across every page (exercises _nav + view wiring).
        for idx in range(len(m.JarvisWindow.VIEW_NAMES)):
            w._nav(idx)
            app.processEvents()
        w._nav(0)

        # State machine cycle (exercises _set_state + HUD surfaces).
        for st in ("listening", "thinking", "processing", "idle"):
            w._set_state(st)
            app.processEvents()

        # Backend status slot (exercises a relocated signal slot + toast).
        w._on_status_signal("smoke-test status")
        app.processEvents()

        # Confirm-card show/hide (exercises _ConfirmMixin UI methods on the real
        # instance, no executor/TTS side effects). The thread-hop itself is
        # covered by tests/test_workflow_thread_hop.py.
        w._show_confirm_card("Smoke confirm?")
        app.processEvents()
        w._hide_confirm_card()
        app.processEvents()

        # Force a resize to dispatch resizeEvent again deterministically.
        w.resize(1300, 820)
        for _ in range(10):
            app.processEvents()

        # ── Assertions ─────────────────────────────────────────────────────
        if counters.get("paintEvent", 0) <= 0:
            failures.append("paintEvent never fired (Qt did not dispatch the override)")
        if counters.get("resizeEvent", 0) <= 0:
            failures.append("resizeEvent never fired")

        # Close → must dispatch closeEvent exactly via the hosting class.
        w.close()
        for _ in range(10):
            app.processEvents()
        if counters.get("closeEvent", 0) <= 0:
            failures.append("closeEvent never fired on window close")

    except Exception as exc:  # noqa: BLE001 — surface any startup/interaction crash
        failures.append(f"exception during smoke: {exc!r}")

    # Self-destruct guard in case anything left the loop spinning.
    QTimer.singleShot(0, app.quit)
    app.processEvents()

    print("=== JarvisWindow launch-smoke ===")
    for v in ("paintEvent", "resizeEvent", "closeEvent", "nativeEvent"):
        print(f"  {v:<12} host={hosts.get(v, '?'):<22} fired={counters.get(v, 0)}")
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
