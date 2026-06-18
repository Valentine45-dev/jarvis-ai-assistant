"""Phase 3 — live interim transcript mirrored into the command bar.

_VoiceMixin._on_transcript_partial paints interim streaming words into the
command-bar input while listening, and the turn-end handlers clear that
dictation. No Qt: the mixin methods are called on a lightweight stand-in that
mimics the bits of JarvisWindow they touch (self._state, self._dashboard...,
self._process_cmd, self._set_state).
"""

from __future__ import annotations

from types import SimpleNamespace

from ui.main_window.voice_mixin import _VoiceMixin


class _FakeInput:
    def __init__(self):
        self.value = ""
        self.cleared = 0

    def setText(self, s):
        self.value = s

    def clear(self):
        self.value = ""
        self.cleared += 1


class _Host(_VoiceMixin):
    """Real _VoiceMixin instance so self._clear_voice_dictation() etc. resolve."""

    def __init__(self, field, state):
        self._state = state
        self._dashboard = SimpleNamespace(
            left=SimpleNamespace(cmd_bar=SimpleNamespace(_input=field)),
            toast=SimpleNamespace(show_toast=lambda *a, **k: None),
        )
        self._processed: list[str] = []
        self._states: list[str] = []

    def _process_cmd(self, text):
        self._processed.append(text)

    def _set_state(self, s):
        self._states.append(s)


def _make_host(state="listening"):
    field = _FakeInput()
    return _Host(field, state), field


# ── _on_transcript_partial ────────────────────────────────────────────────────

def test_partial_paints_into_command_bar_while_listening():
    host, field = _make_host("listening")
    _VoiceMixin._on_transcript_partial(host, "what's the weather")
    assert field.value == "what's the weather"


def test_partial_replaces_previous_interim():
    host, field = _make_host("listening")
    _VoiceMixin._on_transcript_partial(host, "what's the")
    _VoiceMixin._on_transcript_partial(host, "what's the weather in kuwait")
    assert field.value == "what's the weather in kuwait"


def test_partial_ignored_when_not_listening():
    host, field = _make_host("thinking")
    _VoiceMixin._on_transcript_partial(host, "late words")
    assert field.value == ""


def test_blank_partial_ignored():
    host, field = _make_host("listening")
    _VoiceMixin._on_transcript_partial(host, "   ")
    assert field.value == ""


# ── turn-end clears the dictation ─────────────────────────────────────────────

def test_voice_heard_clears_dictation_and_processes():
    host, field = _make_host("listening")
    field.value = "open chrome"           # leftover interim
    _VoiceMixin._on_voice_heard(host, "open chrome")
    assert field.cleared == 1 and field.value == ""
    assert host._processed == ["open chrome"]


def test_voice_error_clears_dictation_and_goes_idle():
    host, field = _make_host("listening")
    field.value = "half a sentence"
    _VoiceMixin._on_voice_error_ui(host, "No speech detected — try speaking louder.")
    assert field.cleared == 1 and field.value == ""
    assert host._states == ["idle"]
