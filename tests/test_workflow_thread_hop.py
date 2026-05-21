"""R2-33: regression test for the Phase 7 workflow thread-hop fix.

Background: when a workflow step calls `request_confirmation`, the user's
"yes" click arrives via a UI/worker thread but the callback (which may
re-enter `dispatch` and touch Playwright's sync API — strictly thread-affine)
MUST run on the Qt main thread. The fix wires
`JarvisWindow._resume_executor_confirm` as a `pyqtSignal(str)` with
`Qt.QueuedConnection`; emitting from any thread queues the slot back onto
the main thread, which then calls `resolve_confirmation("yes")`.

This test verifies the hop holds: it constructs a minimal shim with the
same signal/slot wiring, fires the signal from a worker thread, and asserts
the registered confirmation callback ran on the main thread.
"""

from __future__ import annotations

import threading
from typing import Optional

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal  # noqa: E402

from core.handlers.shared import (  # noqa: E402
    abandon_pending_confirmation,
    request_confirmation,
    resolve_confirmation,
)


pytestmark = pytest.mark.qt


class _WindowShim(QObject):
    """Minimal stand-in for JarvisWindow with the same signal contract."""

    _resume_executor_confirm = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        # QueuedConnection is the load-bearing piece: cross-thread emit must
        # land back on the receiver's owning thread (the main thread here).
        self._resume_executor_confirm.connect(
            self._on_resume_executor_confirm, Qt.QueuedConnection
        )
        self.resolved: Optional[dict] = None

    def _on_resume_executor_confirm(self, answer: str) -> None:
        self.resolved = resolve_confirmation(answer)


def _qt_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_post_confirm_callback_runs_on_main_thread() -> None:
    abandon_pending_confirmation()  # guard against leakage from prior tests
    app = _qt_app()
    main_thread = threading.current_thread()

    callback_thread: dict[str, Optional[threading.Thread]] = {"t": None}
    callback_ran = threading.Event()

    def _confirm_callback() -> dict:
        callback_thread["t"] = threading.current_thread()
        callback_ran.set()
        return {"success": True, "output": "confirmed", "error": ""}

    request_confirmation("Are you sure?", _confirm_callback)

    shim = _WindowShim()

    # Emit from a worker thread — this is the production path: the UI click
    # arrives on whatever thread handles the click event, then must hop.
    def _click_yes_from_worker() -> None:
        shim._resume_executor_confirm.emit("yes")

    worker = threading.Thread(target=_click_yes_from_worker, daemon=True)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive(), "worker thread did not finish its emit"

    # Pump the Qt event loop until the queued slot fires (max ~2s).
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.start(2000)
    while not callback_ran.is_set() and deadline.isActive():
        app.processEvents()

    assert callback_ran.is_set(), "post-confirm callback never ran (thread hop broken?)"
    assert callback_thread["t"] is main_thread, (
        f"callback ran on {callback_thread['t']!r}, expected main thread {main_thread!r} — "
        "the Qt.QueuedConnection hop is no longer enforcing main-thread affinity."
    )
    assert shim.resolved is not None and shim.resolved.get("success") is True


def test_negative_reply_does_not_invoke_callback() -> None:
    abandon_pending_confirmation()
    app = _qt_app()
    callback_ran = threading.Event()

    def _confirm_callback() -> dict:
        callback_ran.set()
        return {"success": True, "output": "should not run", "error": ""}

    request_confirmation("Are you sure?", _confirm_callback)
    shim = _WindowShim()

    threading.Thread(
        target=lambda: shim._resume_executor_confirm.emit("no"),
        daemon=True,
    ).start()

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.start(1500)
    while shim.resolved is None and deadline.isActive():
        app.processEvents()

    assert shim.resolved is not None, "no-reply was never delivered"
    assert callback_ran.is_set() is False, (
        "callback fired on 'no' reply — resolve_confirmation must skip pc.fn() on rejection"
    )
    assert shim.resolved.get("success") is False
