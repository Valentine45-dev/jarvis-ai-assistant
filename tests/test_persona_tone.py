"""Bonus find (during P5 verify): auxiliary LLM prompts leaked the butler 'sir'.

The vision `describe` output said "…the interface itself, sir…", violating the
project tone rule (a sharp warm friend, never 'sir'; address as Valentine). Root
cause: the side-call prompts (vision describe/find, the shared persona constant,
and the post-execution narration tone) never carried the never-'sir' rule the way
the vapi voice prompt already did. These are string-level regression guards so the
rule can't be silently dropped; the real gate is physical (the model stops saying
'sir').
"""

from __future__ import annotations

import core.vision as vision
from core.personality.persona import (
    JARVIS_PERSONA_PROMPT,
    JARVIS_POST_EXECUTION_TONE,
    JARVIS_SHELL_RESULTS_PROMPT,
)


def _has_no_sir_rule(text: str) -> bool:
    t = text.lower()
    return "never" in t and "sir" in t


def test_persona_prompt_forbids_sir():
    assert _has_no_sir_rule(JARVIS_PERSONA_PROMPT)
    assert "valentine" in JARVIS_PERSONA_PROMPT.lower()


def test_shell_results_prompt_inherits_no_sir():
    # built from JARVIS_PERSONA_PROMPT, so it carries the rule
    assert _has_no_sir_rule(JARVIS_SHELL_RESULTS_PROMPT)


def test_post_execution_tone_forbids_sir_and_drops_butler():
    assert _has_no_sir_rule(JARVIS_POST_EXECUTION_TONE)
    # the old "British butler tone" wording (which invited 'sir') is gone
    assert "butler tone" not in JARVIS_POST_EXECUTION_TONE.lower()


def test_vision_describe_prompt_forbids_sir():
    assert _has_no_sir_rule(vision._DESCRIBE_PROMPT)
    assert "valentine" in vision._DESCRIBE_PROMPT.lower()


def test_vision_find_prompt_forbids_sir():
    prompt = vision._build_prompt("find_ui_element", "the submit button")
    assert _has_no_sir_rule(prompt)
