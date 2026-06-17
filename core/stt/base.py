"""Provider-agnostic streaming STT interface.

A StreamingSttSession consumes 16 kHz mono linear16 PCM frames via feed() and
emits transcription events through the callbacks registered in start():

  on_partial(text)       interim (non-final) hypothesis for the current speech
  on_final(text)         a finalized transcript segment
  on_utterance_end()     the provider's endpointing decided speech has ended
  on_error(message)      the stream failed; the caller should fall back

Turn assembly — concatenating final segments and deciding when to hand the full
utterance to the brain — is the CALLER's job. Keeping the session a thin event
mapper is exactly what lets a cloud provider (Deepgram) and a local engine
(Vosk/Whisper) sit behind the same interface: a local engine simply runs its own
endpointing internally and fires on_utterance_end the same way. Swapping
providers is then a one-line change in core/stt/factory.create_stt_session.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

OnPartial = Callable[[str], None]
OnFinal = Callable[[str], None]
OnUtteranceEnd = Callable[[], None]
OnError = Callable[[str], None]


class StreamingSttSession(ABC):
    """One live transcription turn. Not reusable across turns — create a fresh
    session per listen() (cheap; the constructor opens no socket)."""

    @abstractmethod
    def start(
        self,
        *,
        on_partial: OnPartial,
        on_final: OnFinal,
        on_utterance_end: OnUtteranceEnd,
        on_error: OnError,
    ) -> None:
        """Open the stream and begin delivering events on a background thread."""

    @abstractmethod
    def feed(self, pcm16: bytes) -> None:
        """Push raw 16 kHz mono linear16 PCM bytes (exactly what sounddevice's
        int16 RawInputStream yields). No-op once finished/closed."""

    @abstractmethod
    def finish(self) -> None:
        """Flush remaining audio, request a final result, and tear down."""

    @abstractmethod
    def close(self) -> None:
        """Tear down immediately without waiting for a final result."""
