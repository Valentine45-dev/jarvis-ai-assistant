"""Voice / mic / wake-word glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self`` (the composed JarvisWindow instance owns all state and signals).
This module must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations


class _VoiceMixin:
    """Mic capture, STT result handling, wake-word, and TTS-done auto-resume.

    Bodies are moved here in Slice 6; empty until then so the MRO scaffold
    is provable in Slice 1 with zero behaviour change.
    """
