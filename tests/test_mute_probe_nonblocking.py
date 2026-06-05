"""R3-5: the system-mute probe must never block the caller.

say() calls _system_audio_muted() on the Qt main thread. On a cache miss the old
code ran a ≤3 s subprocess synchronously → HUD freeze. The fix returns the cached
value immediately and refreshes in a background daemon, deduped via in_flight.
"""

from __future__ import annotations

import threading
import time
from typing import Iterator

import pytest

import core.voice as v


@pytest.fixture(autouse=True)
def windows_path_empty_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force the Windows probe path and start from an empty/stale cache."""
    monkeypatch.setattr(v, "_OS", "windows")
    with v._probe_lock:
        v._probe_cache["value"] = None
        v._probe_cache["checked_at"] = 0.0
        v._probe_cache["in_flight"] = False
    yield


def _wait_cache_settled(timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with v._probe_lock:
            if not v._probe_cache["in_flight"]:
                return
        time.sleep(0.01)


def test_probe_runs_off_caller_thread_and_returns_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    caller_tid = threading.get_ident()
    probe_tid: dict[str, int] = {}
    done = threading.Event()

    def fake_probe() -> bool:
        probe_tid["tid"] = threading.get_ident()
        time.sleep(0.3)          # simulate the slow subprocess
        done.set()
        return True

    monkeypatch.setattr(v, "_run_mute_probe_subprocess", fake_probe)

    t0 = time.monotonic()
    result = v._probed_system_muted()
    elapsed = time.monotonic() - t0

    assert result is False        # default (unmuted/speak) while the probe is in flight
    assert elapsed < 0.15         # did NOT block on the 0.3 s probe

    assert done.wait(3.0)
    assert probe_tid["tid"] != caller_tid   # ran on a background thread

    _wait_cache_settled()
    with v._probe_lock:
        assert v._probe_cache["value"] is True
        assert v._probe_cache["in_flight"] is False


def test_fresh_cache_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_probe() -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(v, "_run_mute_probe_subprocess", fake_probe)
    with v._probe_lock:
        v._probe_cache["value"] = True
        v._probe_cache["checked_at"] = v._time.monotonic()
        v._probe_cache["in_flight"] = False

    assert v._probed_system_muted() is True
    time.sleep(0.05)
    assert calls["n"] == 0         # fresh cache → no probe at all


def test_concurrent_reads_dedupe_to_one_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    count_lock = threading.Lock()

    def fake_probe() -> bool:
        with count_lock:
            calls["n"] += 1
        time.sleep(0.3)            # stay in flight while the burst of reads happens
        return False

    monkeypatch.setattr(v, "_run_mute_probe_subprocess", fake_probe)

    threads = [threading.Thread(target=v._probed_system_muted) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(2.0)

    _wait_cache_settled()
    assert calls["n"] == 1         # in_flight dedupes the burst to a single probe


def test_non_windows_never_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v, "_OS", "linux")
    called = {"n": 0}
    monkeypatch.setattr(v, "_run_mute_probe_subprocess",
                        lambda: called.__setitem__("n", 1) or True)
    assert v._probed_system_muted() is False
    assert called["n"] == 0
