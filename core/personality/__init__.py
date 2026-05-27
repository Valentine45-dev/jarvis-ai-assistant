"""
JARVIS personality layer — maps (intent, action, success/error) → spoken response.
Uses random.choice() across variant pools so JARVIS never sounds like a bot.

This module was split from a single core/personality.py file (R2-17d) into the
``core/personality`` package. The public API is unchanged:
    from core.personality import say, ask, ack_scheduled_action
    from core.personality import build_response, action_speech_pair
    from core.personality import (
        JARVIS_PERSONA_PROMPT, JARVIS_POST_EXECUTION_TONE, JARVIS_SHELL_RESULTS_PROMPT,
    )

Sub-modules:
  - persona.py — the three persona prompt constants
  - pools.py   — response variant data tables (_P, _DEFAULT, _SCHEDULED_*, _NO_TRIM)
  - render.py  — say / ask / ack_scheduled_action / action_speech_pair / build_response
"""
from __future__ import annotations

from core.personality.persona import (
    JARVIS_PERSONA_PROMPT,
    JARVIS_POST_EXECUTION_TONE,
    JARVIS_SHELL_RESULTS_PROMPT,
)
from core.personality.pools import (
    _DEFAULT,
    _NO_TRIM,
    _P,
    _SCHEDULED_FALLBACK_OK,
    _SCHEDULED_FOLLOWUP,
)
from core.personality.render import (
    _brief_scheduled_output,
    _clean_page_for_speech,
    _is_no_trim_action,
    ack_scheduled_action,
    action_speech_pair,
    ask,
    build_response,
    say,
)

__all__ = [
    "JARVIS_PERSONA_PROMPT",
    "JARVIS_POST_EXECUTION_TONE",
    "JARVIS_SHELL_RESULTS_PROMPT",
    "say",
    "ask",
    "ack_scheduled_action",
    "action_speech_pair",
    "build_response",
]
