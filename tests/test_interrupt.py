"""Esc-to-interrupt: stoppable TTS, cancellable listen, and the UI handler.

No audio, no Qt event loop. The MCI player is exercised with a fake `mci`
callable (it's already a parameter, so no ctypes patching needed); the UI
handler runs on a lightweight stand-in mimicking the bits of JarvisWindow it
touches.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.audio_pipeline import TtsEngine
from core.tts_elevenlabs import _mci_play_until_done
from core.voice import VoiceEngine
from ui.main_window.interrupt_mixin import _InterruptMixin


# ── stoppable TTS ─────────────────────────────────────────────────────────────

def test_stop_speaking_bumps_gen_and_drains_queue():
    eng = TtsEngine()
    fired: list[str] = []
    with eng._speaking_lock:
        eng._speaking_count = 2
    eng._queue.put_nowait(("a", None, lambda: fired.append("a")))
    eng._queue.put_nowait(("b", None, lambda: fired.append("b")))
    g0 = eng._gen

    eng.stop_speaking()

    assert eng._gen == g0 + 1          # the playing clip's poll loop will stop
    assert eng._queue.empty()
    assert eng.is_speaking is False     # counter drained back to 0
    assert set(fired) == {"a", "b"}     # each dropped line's on_done fired


def test_mci_player_stops_on_signal():
    calls: list[str] = []
    polls = {"n": 0}

    def fake_mci(cmd, buf, size, _):
        calls.append(cmd)
        if cmd.startswith("status") and buf is not None:
            buf.value = "playing"
        return 0

    def should_stop():
        polls["n"] += 1
        return polls["n"] >= 3          # stop after a couple of poll cycles

    _mci_play_until_done(fake_mci, "al", should_stop)

    assert any(c == "play al" for c in calls)
    assert any(c == "stop al" for c in calls)   # cut mid-clip


def test_mci_player_finishes_naturally_without_stop():
    calls: list[str] = []
    modes = ["playing", "playing", "stopped"]

    def fake_mci(cmd, buf, size, _):
        calls.append(cmd)
        if cmd.startswith("status") and buf is not None:
            buf.value = modes.pop(0) if modes else "stopped"
        return 0

    _mci_play_until_done(fake_mci, "al", lambda: False)

    assert any(c == "play al" for c in calls)
    assert not any(c == "stop al" for c in calls)   # ran to completion


# ── cancellable listen ────────────────────────────────────────────────────────

class _SilentSession:
    def start(self, **cbs):
        pass

    def feed(self, b):
        pass

    def finish(self):
        self.finished = True

    def close(self):
        pass


class _NoopStreamer:
    def start(self):
        pass

    def stop(self):
        pass


def test_cancel_listening_delivers_nothing():
    eng = VoiceEngine()
    eng._listen_cancel.set()                     # interrupt already requested
    got, errs = [], []
    handled = eng._run_streaming_stt(
        _SilentSession(), got.append, errs.append, 0.5, 0.5,
        mic_streamer=_NoopStreamer(),
    )
    assert handled is True                        # turn handled (not a fallback)
    assert got == [] and errs == []               # no command, no error toast


# ── the interrupt handler ─────────────────────────────────────────────────────

class _FakeField:
    def __init__(self, value=""):
        self.value = value
        self.focused = False

    def text(self):
        return self.value

    def setText(self, s):
        self.value = s

    def setFocus(self):
        self.focused = True


class _FakeTranscript:
    def __init__(self):
        self.rows = []

    def add_interrupted(self, you, t):
        self.rows.append((you, t))


def _make_host(*, state, last, input_text):
    field = _FakeField(input_text)
    transcript = _FakeTranscript()
    dashboard = SimpleNamespace(
        left=SimpleNamespace(
            transcript=transcript,
            cmd_bar=SimpleNamespace(_input=field),
            typing=SimpleNamespace(hide_typing=lambda: None),
            hud_status=SimpleNamespace(set_status=lambda *a: None),
        ),
        toast=SimpleNamespace(show_toast=lambda *a, **k: None),
    )
    host = SimpleNamespace(
        _palette=None,
        _state=state,
        _transcript_update_token=5,
        _last_cmd_text=last,
        _history=[{"status": "pending"}],
        _dashboard=dashboard,
        states=[],
    )
    host._set_state = host.states.append
    return host, field, transcript


def test_interrupt_restores_prompt_logs_and_idles():
    host, field, transcript = _make_host(state="thinking", last="open chrome", input_text="")
    _InterruptMixin._on_interrupt_requested(host)
    assert host._transcript_update_token == 6          # in-flight work invalidated
    assert transcript.rows == [("open chrome", transcript.rows[0][1])]
    assert field.value == "open chrome" and field.focused   # restored (was empty)
    assert host.states == ["idle"]
    assert host._history[-1]["status"] == "interrupted"


def test_interrupt_does_not_clobber_in_progress_typing():
    host, field, _ = _make_host(state="speaking", last="old cmd", input_text="new typing")
    _InterruptMixin._on_interrupt_requested(host)
    assert field.value == "new typing"                 # user's text kept


def test_interrupt_is_noop_when_idle():
    host, field, transcript = _make_host(state="idle", last="x", input_text="")
    _InterruptMixin._on_interrupt_requested(host)
    assert host._transcript_update_token == 5          # untouched
    assert host.states == [] and transcript.rows == []
