"""Streaming speech-to-text — provider-agnostic real-time transcription.

Phase 1 (this package): the StreamingSttSession interface + a Deepgram
implementation + a config-driven factory. Nothing here is wired into the live
voice path yet — VoiceEngine.listen() still uses the legacy Google batch path
until stt_provider is flipped to "deepgram" and Phase 2 wires the streaming loop.
"""

from core.stt.base import StreamingSttSession
from core.stt.factory import create_stt_session

__all__ = ["StreamingSttSession", "create_stt_session"]
