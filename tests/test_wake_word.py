"""R3-15 / R3-16 / R3-17: wake-word detector reliability.

The audio/network I/O is mocked; these exercise the pure orchestration:
  R3-16 — STT errors are classified (UnknownValueError benign vs counted) and a
          run of real failures raises a one-time offline warning that resets on
          the next success.
  R3-17 — _handle_window recognises an injected window and fires the wake
          callback only on a match (and not while paused).
  R3-15 — the _stream_closed handshake event: starts set, clears/sets around a
          simulated stream, and wait_closed honours the timeout.
"""

from __future__ import annotations

import threading

import pytest

from core.wake_word import WakeWordDetector

sr = pytest.importorskip("speech_recognition")


# ── R3-16: failure classification + warn-once ───────────────────────────────

def test_benign_error_is_not_counted() -> None:
    det = WakeWordDetector()
    assert det._stt_error_benign(sr.UnknownValueError()) is True
    assert det._stt_error_benign(RuntimeError("network")) is False
    for _ in range(10):
        det._note_stt_failure(benign=True)
    assert det._fail_count == 0
    assert det._warned_offline is False


def test_real_failures_warn_once_at_threshold() -> None:
    det = WakeWordDetector()
    warnings: list[int] = []
    det._emit_offline_warning = lambda: warnings.append(det._fail_count)  # type: ignore[method-assign]

    for _ in range(det.OFFLINE_THRESHOLD - 1):
        det._note_stt_failure(benign=False)
    assert warnings == []                       # not yet at threshold

    det._note_stt_failure(benign=False)         # crosses threshold
    assert warnings == [det.OFFLINE_THRESHOLD]

    det._note_stt_failure(benign=False)         # already warned → no repeat
    assert warnings == [det.OFFLINE_THRESHOLD]


def test_success_resets_failure_streak() -> None:
    det = WakeWordDetector()
    warnings: list[int] = []
    det._emit_offline_warning = lambda: warnings.append(1)  # type: ignore[method-assign]

    for _ in range(det.OFFLINE_THRESHOLD):
        det._note_stt_failure(benign=False)
    assert warnings == [1]

    det._note_stt_success()
    assert det._fail_count == 0
    assert det._warned_offline is False

    # A fresh streak can warn again after recovery.
    for _ in range(det.OFFLINE_THRESHOLD):
        det._note_stt_failure(benign=False)
    assert warnings == [1, 1]


def test_handle_window_failure_path_counts_and_logs() -> None:
    det = WakeWordDetector()
    fired: list[bool] = []
    det._callback = lambda: fired.append(True)

    def boom(_frames: bytes) -> str:
        raise RuntimeError("network down")

    det._handle_window(b"x", transcribe=boom, wake_word="jarvis")
    assert fired == []                          # no wake on error
    assert det._fail_count == 1                 # counted (non-benign)


# ── R3-17: recognise + wake match via _handle_window ────────────────────────

def test_handle_window_fires_callback_on_match() -> None:
    det = WakeWordDetector()
    fired: list[bool] = []
    det._callback = lambda: fired.append(True)

    det._handle_window(b"x", transcribe=lambda _f: "hey jarvis are you there",
                       wake_word="jarvis")
    assert fired == [True]
    assert det._paused.is_set()                 # paused itself before the callback
    assert det._fail_count == 0                 # success reset


def test_handle_window_no_callback_without_match() -> None:
    det = WakeWordDetector()
    fired: list[bool] = []
    det._callback = lambda: fired.append(True)

    det._handle_window(b"x", transcribe=lambda _f: "what time is it",
                       wake_word="jarvis")
    assert fired == []


def test_handle_window_skips_when_paused() -> None:
    det = WakeWordDetector()
    fired: list[bool] = []
    det._callback = lambda: fired.append(True)
    det.pause()                                 # main owns the mic

    det._handle_window(b"x", transcribe=lambda _f: "jarvis",
                       wake_word="jarvis")
    assert fired == []                          # must not fire while paused


def test_pause_drops_pending_window() -> None:
    det = WakeWordDetector()
    with det._mailbox_cv:
        det._pending_frames = b"stale"
    det.pause()
    assert det._pending_frames is None


# ── R3-15: stream-closed handshake ──────────────────────────────────────────

def test_stream_closed_starts_set() -> None:
    det = WakeWordDetector()
    assert det.wait_closed(0.01) is True        # no stream open at construction


def test_wait_closed_times_out_while_open() -> None:
    det = WakeWordDetector()
    det._stream_closed.clear()                  # simulate "stream open"
    assert det.wait_closed(0.05) is False       # honours timeout, doesn't hang


def test_wait_closed_returns_when_set_from_another_thread() -> None:
    det = WakeWordDetector()
    det._stream_closed.clear()

    def closer() -> None:
        det._stream_closed.set()

    threading.Timer(0.05, closer).start()
    assert det.wait_closed(2.0) is True         # unblocks once the stream closes
