"""Command execution pipeline for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations


class _ExecutionMixin:
    """Brain-result handling, dispatch, finish-execute, TTS lockstep, and
    post-execution narration.

    IMPORTANT (thread affinity): every ``dispatch()`` / ``browser.*`` call in
    these methods must remain on the Qt main thread — do not introduce worker
    threads here. Bodies are moved in Slice 8; empty until then.
    """
