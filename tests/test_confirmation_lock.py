"""R2-35: regression test for Phase 6 pending-confirmation lock.

Background: `core.handlers.shared` holds a single `_pending_confirmation`
slot guarded by `_pending_lock`. The contract is:

  1. Only one confirmation can be pending at a time. A second
     `request_confirmation` replaces the slot atomically.
  2. `resolve_confirmation` pops the slot under the lock BEFORE invoking
     `pc.fn()` so two callbacks can never execute concurrently.
  3. The slot is `None` between resolutions — no leak across runs.

This test hammers the API from 10 worker threads in randomised order and
asserts the invariants hold.
"""

from __future__ import annotations

import random
import threading
import time

import pytest

from core.handlers.shared import (
    abandon_pending_confirmation,
    get_pending_confirmation,
    request_confirmation,
    resolve_confirmation,
)


@pytest.fixture(autouse=True)
def _clean_slot() -> None:
    """Make sure no stale pending slot leaks in from another test."""
    abandon_pending_confirmation()


def test_each_callback_invoked_at_most_once() -> None:
    """Atomic pop: a single registered callback can never fire twice, even
    when many threads race `request_confirmation` / `resolve_confirmation`.

    Note: `resolve_confirmation` deliberately releases the lock before
    invoking `pc.fn()` so callbacks can re-enter the confirmation API
    without deadlocking. The serialisation guarantee is therefore at the
    *slot* level (one resolve = one popped pc), not at the *callback*
    execution level. This test asserts the slot-level invariant.
    """
    fire_count: dict[int, int] = {}
    fire_count_lock = threading.Lock()

    def _make_callback(idx: int):
        def _cb() -> dict:
            with fire_count_lock:
                fire_count[idx] = fire_count.get(idx, 0) + 1
            # Hold briefly so concurrent resolves overlap and stress the pop.
            time.sleep(0.002)
            return {"success": True, "output": f"cb-{idx}", "error": ""}
        return _cb

    def _worker(seed: int) -> None:
        rng = random.Random(seed)
        for i in range(20):
            op = rng.choice(("request", "resolve"))
            if op == "request":
                request_confirmation(f"prompt {seed}-{i}", _make_callback(seed * 100 + i))
            else:
                resolve_confirmation("yes")
            time.sleep(rng.uniform(0, 0.002))

    threads = [threading.Thread(target=_worker, args=(s,), daemon=True) for s in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "worker hung — possible deadlock in _pending_lock"

    # The hard invariant: no callback was popped + invoked twice.
    duplicates = {idx: n for idx, n in fire_count.items() if n > 1}
    assert not duplicates, (
        f"Callbacks fired more than once: {duplicates}. "
        "resolve_confirmation's atomic pop guarantee is broken — a single "
        "_pending_confirmation slot was consumed by two threads."
    )
    # Soft sanity check: at least one callback actually fired.
    assert sum(fire_count.values()) > 0


def test_slot_does_not_leak_between_resolutions() -> None:
    """After every resolve, the pending slot must be None until the next request."""
    for _ in range(50):
        request_confirmation("p", lambda: {"success": True, "output": "ok", "error": ""})
        assert get_pending_confirmation() is not None
        resolve_confirmation("yes")
        assert get_pending_confirmation() is None, (
            "Pending slot survived resolve_confirmation — clear-before-fn-call "
            "ordering may be broken."
        )


def test_second_request_replaces_first_atomically() -> None:
    """A new request_confirmation must overwrite the prior unresolved slot."""
    first_fired = threading.Event()
    second_fired = threading.Event()

    def _first() -> dict:
        first_fired.set()
        return {"success": True, "output": "first", "error": ""}

    def _second() -> dict:
        second_fired.set()
        return {"success": True, "output": "second", "error": ""}

    request_confirmation("first", _first)
    request_confirmation("second", _second)

    result = resolve_confirmation("yes")
    assert second_fired.is_set(), "the second request's callback did not run"
    assert not first_fired.is_set(), (
        "the first callback ran — request_confirmation isn't atomically replacing the slot."
    )
    assert result.get("output") == "second"


def test_resolve_with_no_pending_returns_error() -> None:
    """Resolving when nothing is pending must surface a clear error, not crash."""
    abandon_pending_confirmation()
    out = resolve_confirmation("yes")
    assert out.get("success") is False
    assert "no pending" in (out.get("error") or "").lower()
