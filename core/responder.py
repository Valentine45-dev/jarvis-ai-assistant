"""Context-aware response assembler for JARVIS."""
from __future__ import annotations

from typing import Optional

from core.responder_utils import (
    _OUTPUT_IS_RESPONSE,
    _SUPPRESS_FOLLOW,
    data_follow,
    first_sentence,
    in_rule_set,
    smart_error,
    speech_compact,
    tts_safe_output,
)

class ResponseAssembler:
    """Assembles (primary, follow) spoken response for any JARVIS command."""

    def build(
        self,
        intent: str,
        action: str,
        exec_ok: bool,
        claude_response: str,
        output: str = "",
        error: str = "",
        params: Optional[dict] = None,
        last_step: Optional[tuple] = None,
    ) -> tuple[str, Optional[str]]:
        """
        Returns (primary_tts, follow_tts | None).

        primary is guaranteed non-empty.
        follow is None unless it adds actionable result data.
        """
        params = params or {}

        # ── Error path ────────────────────────────────────────────────────────
        if not exec_ok:
            return (speech_compact(smart_error(intent, action, error, params)), None)

        # ── Output-IS-response (listings, OCR, code, read_page) ──────────────
        if in_rule_set(intent, action, _OUTPUT_IS_RESPONSE):
            from core.personality import say as _pool_say
            tts_out = tts_safe_output(output) if intent == "code_execution" else output
            return (speech_compact(_pool_say(intent, action, "ok", tts_out, error)), None)

        # ── Standard path: Claude primary + optional data-rich follow ─────────
        primary = first_sentence((claude_response or "").strip())
        if not primary:
            from core.personality import say as _pool_say
            primary = _pool_say(intent, action, "ok", output, error)
        primary = speech_compact(primary)

        # Suppress follow-up for self-contained responses
        if in_rule_set(intent, action, _SUPPRESS_FOLLOW):
            return (primary, None)

        # Build data-rich follow-up
        follow = data_follow(intent, action, output, params)
        return (primary, speech_compact(follow) if follow else None)

    def build_scheduled(
        self,
        intent: str,
        action: str,
        exec_ok: bool,
        output: str = "",
        error: str = "",
        params: Optional[dict] = None,
    ) -> str:
        """
        Single spoken line for reminder-fired (scheduled) actions.
        Always returns a non-empty string.
        """
        params = params or {}

        if not exec_ok:
            return speech_compact(smart_error(intent, action, error, params))

        follow = data_follow(intent, action, output, params)
        if follow:
            return speech_compact(follow)

        # Fallback: personality pool for scheduled actions
        from core.personality import ack_scheduled_action
        return speech_compact(ack_scheduled_action(intent, action, True, output, error))


responder = ResponseAssembler()
