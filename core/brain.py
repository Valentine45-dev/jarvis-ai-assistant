"""
Claude API connector — ask_claude(input) → parsed JSON intent dict.

Pipeline per call:
  1. STT normalisation (whitespace / punctuation collapse)
  2. @tag extraction  → intent override + cleaned text
  3. Context assembly → tag_override, os, optional window/clipboard/history
  4. Claude API call  → raw JSON string
  5. Parse + validate → intent dict
  6. Tag enforcement  → override intent if Claude ignored context.tag_override
"""

from __future__ import annotations

import json
import platform
import re
import threading
from pathlib import Path
from typing import Any

import anthropic

from config.settings import config
from core.memory import memory

# ── System prompt ─────────────────────────────────────────────────────────────

_CLAUDE_MD = Path(__file__).parent.parent / "Claude.md"

# Cached system prompt — read once, reused every call.
_system_prompt_text: str | None = None


def _get_system_prompt() -> str:
    global _system_prompt_text
    if _system_prompt_text is None:
        try:
            _system_prompt_text = _CLAUDE_MD.read_text(encoding="utf-8")
        except Exception:
            _system_prompt_text = (
                "You are JARVIS. Return a single valid JSON object only. "
                "No markdown, no code fences, no explanations."
            )
    return _system_prompt_text


# ── @tag routing ──────────────────────────────────────────────────────────────

# Source of truth.  Claude.md's @TAG ROUTING section is derived from this dict.
# Keep both in sync when adding new intents.
TAG_INTENT_MAP: dict[str, str] = {
    "browser":  "browser_automation",
    "search":   "search_web",
    "files":    "file_operation",
    "system":   "system_control",
    "code":     "code_execution",
    "mouse":    "control_mouse",
    "type":     "type_text",
    "app":      "open_app",
    "automate": "automation_task",
    "screen":   "read_screen",
    "remind":   "reminder_task",
    "jarvis":   "jarvis_meta",
}


def extract_tag(text: str) -> tuple[str | None, str]:
    """Return (intent_override | None, cleaned_text).

    Handles two forms:
      - Typed:  "@Browser check the news"  → ("browser_automation", "check the news")
      - Voice:  "at browser check the news" → ("browser_automation", "check the news")

    If the tag is present but unrecognised, returns (None, original_text) so
    the caller can show a warning rather than silently misfiring.
    """
    text = text.strip()

    if text.startswith("@"):
        parts = text.split(" ", 1)
        tag = parts[0][1:].lower()
        remainder = parts[1].strip() if len(parts) > 1 else ""
        intent = TAG_INTENT_MAP.get(tag)
        if intent:
            return intent, remainder
        # Unrecognised @tag — signal with sentinel so caller can warn the user.
        return f"__unknown_tag__{tag}", text

    # Voice-transcribed form: "at <tag> ..."
    lower = text.lower()
    for tag, intent in TAG_INTENT_MAP.items():
        prefix = f"at {tag} "
        if lower.startswith(prefix):
            return intent, text[len(prefix):].strip()

    return None, text


# ── Context builder ───────────────────────────────────────────────────────────

def build_context(
    tag_override: str | None = None,
    active_window: str | None = None,
    clipboard: str | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {"os": platform.system().lower()}
    if tag_override:
        ctx["tag_override"] = tag_override
    if active_window:
        ctx["active_window"] = active_window
    if clipboard:
        ctx["clipboard"] = clipboard
    return ctx


# ── Claude client (lazy, invalidated when key changes) ───────────────────────

_client: anthropic.Anthropic | None = None
_client_key: str = ""


def _get_client() -> anthropic.Anthropic:
    global _client, _client_key
    key = config.anthropic_api_key
    if _client is None or key != _client_key:
        _client = anthropic.Anthropic(api_key=key)
        _client_key = key
    return _client


# ── Public API ────────────────────────────────────────────────────────────────

def ask_claude(
    raw_input: str,
    context: dict[str, Any] | None = None,
    *,
    active_window: str | None = None,
    clipboard: str | None = None,
) -> dict[str, Any]:
    """Route raw_input through the @tag pre-processor, then call Claude.

    Returns a parsed intent dict. Never raises — returns an 'unknown'
    fallback on any error so the executor always receives valid data.
    """
    # 1. STT normalisation (v2.1 Rule 11)
    text = re.sub(r"\s+", " ", raw_input.strip())
    text = re.sub(r"([.!?])\1+", r"\1", text)

    # 2. @tag extraction
    tag_result, cleaned = extract_tag(text)

    # Unrecognised tag sentinel — pass through to NLP, surface warning via _error
    unrecognised_tag: str | None = None
    if isinstance(tag_result, str) and tag_result.startswith("__unknown_tag__"):
        unrecognised_tag = tag_result.replace("__unknown_tag__", "")
        tag_result = None
        cleaned = text

    tag_override: str | None = tag_result

    # 3. Context assembly (per-call metadata — not stored in history)
    ctx = build_context(
        tag_override=tag_override,
        active_window=active_window,
        clipboard=clipboard,
    )
    if context:
        ctx.update(context)

    # Inject last read_page result so Claude can answer follow-up "what does it say"
    try:
        from core.executor import get_page_cache
        cached_page = get_page_cache()
        if cached_page:
            ctx["last_page_content"] = cached_page[:600]
    except Exception:
        pass

    # 4. Compose user message — cmd_text stored in history; full user_msg sent to Claude
    cmd_text = cleaned if cleaned else text
    user_msg = cmd_text
    if ctx:
        user_msg += f"\n\ncontext: {json.dumps(ctx)}"

    # 5. Call Claude — prepend conversation history for multi-turn context.
    #    The system prompt is large (~1 500 tokens); cache_control keeps it
    #    cached for 5 minutes so repeated commands pay ~0.1× input cost.
    raw = ""
    try:
        msg = _get_client().messages.create(
            model=config.claude_model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _get_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=memory.get_messages() + [{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()

        # Strip accidental markdown fences that slip through
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        result: dict[str, Any] = json.loads(raw)
        memory.add_exchange(cmd_text, raw)

    except json.JSONDecodeError as exc:
        if config.debug_mode:
            print(f"[brain] JSON parse error: {exc}\nRaw: {raw!r}")
        result = _fallback("json_parse_error", raw_input)

    except anthropic.AuthenticationError:
        result = _fallback("invalid_api_key", raw_input)

    except anthropic.RateLimitError:
        result = _fallback("rate_limited", raw_input)

    except anthropic.APIStatusError as exc:
        if config.debug_mode:
            print(f"[brain] API status {exc.status_code}: {exc.message}")
        result = _fallback(f"api_error_{exc.status_code}", raw_input)

    except Exception as exc:
        if config.debug_mode:
            print(f"[brain] API error: {exc}")
        result = _fallback(str(exc), raw_input)

    # 6. Tag enforcement — if Claude ignored context.tag_override, force it
    if tag_override and result.get("intent") != tag_override:
        result["intent"] = tag_override
        result["confidence"] = min(
            1.0, float(result.get("confidence", 0.85)) + 0.05
        )
        if config.debug_mode:
            print(f"[brain] @tag enforced override → {tag_override}")

    # Surface unrecognised tag warning via a sideband field (never breaks routing)
    if unrecognised_tag:
        result["_unknown_tag"] = unrecognised_tag

    return result


def ask_claude_async(
    raw_input: str,
    callback,
    **kwargs,
) -> None:
    """Non-blocking variant: runs ask_claude in a daemon thread.

    callback(result: dict) is called from the worker thread — callers that
    update Qt widgets must use QMetaObject.invokeMethod or a signal/slot.
    """
    def _worker():
        result = ask_claude(raw_input, **kwargs)
        callback(result)

    threading.Thread(target=_worker, daemon=True).start()


# ── Fallback ──────────────────────────────────────────────────────────────────

def _fallback(reason: str, original: str) -> dict[str, Any]:
    return {
        "intent": "unknown",
        "action": "none",
        "parameters": {},
        "confidence": 0.05,
        "response": "I'm unable to process that request.",
        "hud_status": "UNKNOWN",
        "requires_confirmation": False,
        "_error": reason,
        "_original_input": original,
    }
