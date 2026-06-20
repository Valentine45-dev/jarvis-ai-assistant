"""Tests for moving code_execution off the Qt main thread (worker + confirm round-trip).

Background: code_execution used to run synchronously inside ``dispatch()`` on the Qt
main thread, freezing the UI for the length of any subprocess. It now runs on a daemon
worker thread; the result returns via ``signals.code_execution_done`` to a main-thread
slot that either finishes the command or shows a confirm card whose "yes" re-enters the
SAME worker helper. See ui/main_window/execution_mixin.py + confirm_mixin.py.

These tests exercise the routing logic directly (calling the mixin methods on a light
stub) for determinism, plus one real-threading test of the spawn helper and one test of
the Esc generation-gate that suppresses ghost terminal output from an orphaned worker.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

pytest.importorskip("PyQt5")

from ui.main_window.confirm_mixin import _ConfirmMixin  # noqa: E402
from ui.main_window.execution_mixin import _ExecutionMixin  # noqa: E402

# ── stub plumbing ───────────────────────────────────────────────────────────


class _Rec:
    """Callable that records every invocation."""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append((a, k))

    @property
    def count(self):
        return len(self.calls)


class _FakeSig:
    """Stand-in for a pyqtSignal — records ``emit`` payloads with no event loop.

    Cross-thread delivery of a real pyqtSignal to a plain Python callable needs a
    running Qt event loop; monkeypatching the signal object onto ``signals`` lets the
    worker/reader thread record synchronously instead (GIL-safe list append).
    """

    def __init__(self):
        self.emitted = []
        self.event = threading.Event()

    def emit(self, *args):
        self.emitted.append(args[0] if len(args) == 1 else args)
        self.event.set()

    @property
    def count(self):
        return len(self.emitted)


def _make_stub(*, auto_confirm=False, scripted=None):
    """A SimpleNamespace carrying just the attributes the slot/confirm methods touch.

    ``scripted`` is a list of exec_out dicts the *stubbed* ``_spawn_code_worker`` will
    feed back through ``_on_code_execution_done`` (synchronously, on this thread) to
    simulate successive worker results — driving the confirm round-trip without threads.
    """
    stub = types.SimpleNamespace()
    stub._code_exec_in_flight = False
    stub._code_exec_flight_token = -1
    stub._code_exec_confirm_ctx = None
    stub._transcript_update_token = 0
    stub._auto_confirm = auto_confirm
    stub._confirm_mode = None
    stub._pending_result = None
    stub._last_result = None
    stub._history = []
    stub._state = "processing"
    stub._ACTION_INTENTS = {"code_execution"}

    stub._finish_execute = _Rec()
    stub._show_confirm_card = _Rec()
    stub._hide_confirm_card = _Rec()
    stub._tts_ready = types.SimpleNamespace(emit=_Rec())

    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            typing=types.SimpleNamespace(hide_typing=_Rec()),
        ),
        toast=types.SimpleNamespace(show_toast=_Rec()),
    )
    stub._confirmation_controller = types.SimpleNamespace(
        prompt_from_result=lambda exec_out: exec_out.get("output") or "Confirm?",
    )

    # Stubbed spawn: mirror the REAL helper's flag bookkeeping, then (if scripted)
    # synchronously drive the next worker result back into the slot.
    stub._spawn_calls = []
    stub._scripted = list(scripted or [])

    def _spawn(run_callable, *, result, intent, conf, resp, hud):
        stub._spawn_calls.append(
            {"callable": run_callable, "result": result, "intent": intent}
        )
        token = stub._transcript_update_token
        stub._code_exec_in_flight = True
        stub._code_exec_flight_token = token
        if stub._scripted:
            nxt = stub._scripted.pop(0)
            _ExecutionMixin._on_code_execution_done(
                stub,
                {
                    "exec_out": nxt, "result": result, "intent": intent,
                    "conf": conf, "resp": resp, "hud": hud, "token": token,
                },
            )

    stub._spawn_code_worker = _spawn
    return stub


def _payload(exec_out, *, token=0, result=None, intent="code_execution"):
    return {
        "exec_out": exec_out,
        "result": result or {"intent": intent, "action": "run_shell"},
        "intent": intent, "conf": 0.9, "resp": "ok", "hud": "EXECUTING",
        "token": token,
    }


@pytest.fixture(autouse=True)
def _silence_collaborators(monkeypatch):
    """Keep the slot's optional collaborators (TTS, memory) inert during tests."""
    import core.memory
    import core.voice
    monkeypatch.setattr(core.voice.voice_engine, "say", lambda *a, **k: None)
    monkeypatch.setattr(core.memory.memory, "inject_outcome", lambda **k: None)


# ── 1. off-thread spawn (real helper) ───────────────────────────────────────


def test_spawn_runs_off_thread_and_emits_result(monkeypatch):
    from core.signals import signals

    fake = _FakeSig()
    monkeypatch.setattr(signals, "code_execution_done", fake)

    stub = types.SimpleNamespace()
    stub._transcript_update_token = 7
    stub._code_exec_in_flight = False
    stub._code_exec_flight_token = -1
    stub._finish_execute = _Rec()

    caller = threading.current_thread()
    ran_on = {}

    def _callable():
        ran_on["t"] = threading.current_thread()
        return {"success": True, "output": "done", "error": ""}

    result = {"intent": "code_execution", "action": "run_shell"}
    _ExecutionMixin._spawn_code_worker(
        stub, _callable,
        result=result, intent="code_execution", conf=0.9, resp="ok", hud="EXECUTING",
    )

    # Flag bookkeeping happens synchronously on the calling (main) thread.
    assert stub._code_exec_in_flight is True
    assert stub._code_exec_flight_token == 7
    # Real subprocess work never finishes inline.
    assert stub._finish_execute.count == 0

    assert fake.event.wait(timeout=3.0), "worker never emitted code_execution_done"
    payload = fake.emitted[0]
    assert payload["exec_out"] == {"success": True, "output": "done", "error": ""}
    assert payload["token"] == 7
    assert ran_on["t"] is not caller, "callable must run on the worker thread, not the caller"


# ── 2. final result finishes + releases the guard ───────────────────────────


def test_final_result_finishes_and_clears_guard():
    stub = _make_stub()
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 0

    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"success": True, "output": "hi", "error": ""}, token=0)
    )

    assert stub._finish_execute.count == 1
    assert stub._code_exec_in_flight is False
    assert stub._last_result is not None  # success + action intent → remembered


# ── 3. needs-confirmation shows the card, keeps the guard, stashes context ───


def test_needs_confirmation_shows_card_and_holds_guard():
    stub = _make_stub()
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 0
    real_result = {"intent": "code_execution", "action": "run_powershell"}

    _ExecutionMixin._on_code_execution_done(
        stub,
        _payload(
            {"needs_confirmation": True, "output": "Run PowerShell?"},
            token=0, result=real_result,
        ),
    )

    assert stub._show_confirm_card.count == 1
    assert stub._confirm_mode == "executor_code"
    assert stub._code_exec_in_flight is True, "guard must stay set across the card"
    assert stub._finish_execute.count == 0
    # The real brain context is stashed for the post-confirm re-run.
    assert stub._code_exec_confirm_ctx["result"] is real_result


# ── 4. single-hop round-trip: confirm re-enters the worker, not inline ───────


def test_confirm_round_trip_respawns_then_finishes():
    # The confirm's worker "returns" a final success result (scripted).
    stub = _make_stub(scripted=[{"success": True, "output": "ran", "error": ""}])
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 0

    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"needs_confirmation": True, "output": "Run?"}, token=0)
    )
    assert stub._confirm_mode == "executor_code"
    assert stub._finish_execute.count == 0

    # User clicks "Yes".
    _ConfirmMixin._on_confirmed(stub)

    # The confirm re-entered the worker (with a callable), NOT an inline resolve.
    assert len(stub._spawn_calls) == 1
    assert callable(stub._spawn_calls[0]["callable"])
    # The scripted final result then flowed through the slot to finish.
    assert stub._finish_execute.count == 1
    assert stub._code_exec_in_flight is False
    assert stub._code_exec_confirm_ctx is None


# ── 5. multi-hop round-trip: confirm → needs_confirmation → confirm → final ──


def test_multi_hop_round_trip_guard_holds_until_final():
    # Hop 1 confirm → worker returns ANOTHER needs_confirmation;
    # hop 2 confirm → worker returns the final result.
    stub = _make_stub(scripted=[
        {"needs_confirmation": True, "output": "Second confirm?"},
        {"success": True, "output": "finally", "error": ""},
    ])
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 0

    # First card.
    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"needs_confirmation": True, "output": "First confirm?"}, token=0)
    )
    assert stub._show_confirm_card.count == 1
    assert stub._code_exec_in_flight is True

    # First confirm → spawn → scripted 2nd needs_confirmation → second card.
    _ConfirmMixin._on_confirmed(stub)
    assert stub._show_confirm_card.count == 2
    assert stub._confirm_mode == "executor_code"
    assert stub._code_exec_in_flight is True, "guard must persist between hops"
    assert stub._finish_execute.count == 0

    # Second confirm → spawn → scripted final → finish.
    _ConfirmMixin._on_confirmed(stub)
    assert stub._finish_execute.count == 1
    assert stub._code_exec_in_flight is False, "guard clears only on the final result"


# ── 6. auto-confirm re-spawns off-thread (never resolves on the main thread) ─


def test_auto_confirm_respawns_without_card():
    stub = _make_stub(auto_confirm=True)  # no scripted → spawn just records
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 0

    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"needs_confirmation": True, "output": "Run?"}, token=0)
    )

    assert len(stub._spawn_calls) == 1, "auto-confirm must re-enter the worker"
    assert callable(stub._spawn_calls[0]["callable"])
    assert stub._show_confirm_card.count == 0
    assert stub._confirm_mode != "executor_code"
    assert stub._finish_execute.count == 0


# ── 7. _process_cmd rejects a new command while a worker is in flight ────────


def test_process_cmd_blocked_while_in_flight():
    from core.handlers.shared import abandon_pending_confirmation
    abandon_pending_confirmation()  # ensure no leaked pending confirmation

    stub = _make_stub()
    stub._state = "idle"
    stub._code_exec_in_flight = True
    # Attributes _process_cmd reads before reaching the in-flight guard.
    stub._cmd_from_terminal = False
    stub._command_controller = types.SimpleNamespace(
        parse_command=lambda cmd: (None, cmd),
    )

    _ExecutionMixin._process_cmd(stub, "echo hi")

    msgs = [a[0] for (a, k) in stub._dashboard.toast.show_toast.calls]
    assert any("command is running" in m.lower() for m in msgs)
    # Returned before doing any real work — the transcript token is untouched.
    assert stub._transcript_update_token == 0


# ── 8. stale token (Esc / superseded) drops the result ──────────────────────


def test_stale_token_drops_result_and_releases_owner_guard():
    stub = _make_stub()
    stub._transcript_update_token = 9  # a newer command bumped it
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 5  # this payload owns the guard

    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"success": True, "output": "late", "error": ""}, token=5)
    )

    assert stub._finish_execute.count == 0, "stale result must not finish"
    assert stub._code_exec_in_flight is False, "owner payload releases its own guard"


def test_stale_token_does_not_clear_a_newer_commands_guard():
    stub = _make_stub()
    stub._transcript_update_token = 9
    stub._code_exec_in_flight = True
    stub._code_exec_flight_token = 8  # a NEWER command owns the guard now

    _ExecutionMixin._on_code_execution_done(
        stub, _payload({"success": True, "output": "late", "error": ""}, token=5)
    )

    assert stub._finish_execute.count == 0
    assert stub._code_exec_in_flight is True, "orphan must not clear a newer guard"


# ── 9. generation gate: cancelled run suppresses the terminal stream ─────────


def test_cancelled_generation_suppresses_terminal_emits(monkeypatch):
    import core.handlers.code_exec as ce
    from core.signals import signals

    # Snapshot returns 0; every later call returns 1 → the run looks cancelled.
    calls = {"n": 0}

    def _fake_gen():
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 1

    monkeypatch.setattr(ce, "current_exec_generation", _fake_gen)

    lines, done = _FakeSig(), _FakeSig()
    monkeypatch.setattr(signals, "terminal_line_ready", lines)
    monkeypatch.setattr(signals, "terminal_done", done)

    out, code, _ms = ce._stream_execute(
        [sys.executable, "-c", "print('ghost-line')"], None, timeout=10
    )

    # The output is still captured internally (pipe is drained)…
    assert "ghost-line" in out
    assert code == 0
    # …but NOTHING was painted to the terminal because the generation moved on.
    assert lines.count == 0, "ghost output leaked after cancel"
    assert done.count == 0, "exit-code badge leaked after cancel"


def test_uncancelled_generation_streams_normally(monkeypatch):
    """Contrast: with the generation untouched, output streams as usual."""
    import core.handlers.code_exec as ce
    from core.signals import signals

    lines, done = _FakeSig(), _FakeSig()
    monkeypatch.setattr(signals, "terminal_line_ready", lines)
    monkeypatch.setattr(signals, "terminal_done", done)

    out, code, _ms = ce._stream_execute(
        [sys.executable, "-c", "print('live-line')"], None, timeout=10
    )

    assert "live-line" in out
    assert code == 0
    assert lines.count >= 1, "live output should stream when not cancelled"
    assert done.count == 1


# ── Phase 3: Esc kills the running foreground subprocess ─────────────────────


def test_clear_foreground_only_clears_matching_proc():
    import core.handlers.code_exec as ce

    p1, p2 = object(), object()
    ce._register_foreground(p1)
    try:
        ce._clear_foreground(p2)  # a different proc → must NOT clear p1
        with ce._foreground_lock:
            assert ce._foreground_proc is p1
        ce._clear_foreground(p1)  # the matching proc → cleared
        with ce._foreground_lock:
            assert ce._foreground_proc is None
    finally:
        ce._clear_foreground(p1)  # belt-and-suspenders cleanup


def test_cancel_without_foreground_just_bumps_generation(monkeypatch):
    import core.handlers.code_exec as ce

    monkeypatch.setattr(ce, "_foreground_proc", None, raising=False)
    before = ce.current_exec_generation()
    ce.cancel_active_execution()  # must not raise with nothing running
    assert ce.current_exec_generation() == before + 1


def test_cancel_kills_running_foreground_subprocess(monkeypatch):
    import core.handlers.code_exec as ce
    from core.signals import signals

    # No event loop here — keep the terminal signals inert.
    monkeypatch.setattr(signals, "terminal_line_ready", _FakeSig())
    monkeypatch.setattr(signals, "terminal_done", _FakeSig())

    result = {}

    def _run():
        out, code, ms = ce._stream_execute(
            [sys.executable, "-c", "import time; time.sleep(30)"], None, timeout=60
        )
        result.update(out=out, code=code, ms=ms)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()

    # Wait until _stream_execute has registered its live proc.
    proc = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with ce._foreground_lock:
            proc = ce._foreground_proc
        if proc is not None:
            break
        time.sleep(0.02)
    assert proc is not None, "foreground proc was never registered"

    # Esc → cancel_active_execution kills the whole tree.
    ce.cancel_active_execution()

    worker.join(timeout=10.0)
    assert not worker.is_alive(), "_stream_execute did not return after the kill"
    # Returned WELL before the 30s sleep / 60s timeout — i.e. it was actually killed.
    assert result["ms"] < 15000, "command was not killed promptly"
    # The handle is cleared on exit.
    with ce._foreground_lock:
        assert ce._foreground_proc is None
