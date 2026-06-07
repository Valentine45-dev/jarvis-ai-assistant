"""list_tabs should SPEAK the actual tab list, not a generic "pulling up tabs"
ack. It's wired into _OUTPUT_IS_RESPONSE, and render._clean_tabs_for_speech
turns the terminal listing (numbered, with '*' markers + the '(* = active)'
legend) into a natural spoken sentence.
"""

from __future__ import annotations

from core.personality.render import _clean_tabs_for_speech, say
from core.responders.assembler import responder
from core.responders.utils import _OUTPUT_IS_RESPONSE, in_rule_set

SAMPLE = (
    "2 tabs open (* = active):\n"
    "  1. about:blank — (no title)\n"
    "  2. github.com — GitHub *"
)


def test_list_tabs_in_output_is_response() -> None:
    assert in_rule_set("browser_automation", "list_tabs", _OUTPUT_IS_RESPONSE)


def test_clean_tabs_for_speech_basic() -> None:
    spoken = _clean_tabs_for_speech(SAMPLE)
    assert spoken == "2 tabs open: a blank tab; GitHub, active."


def test_clean_tabs_marks_active_by_title() -> None:
    out = (
        "3 tabs open (* = active):\n"
        "  1. youtube.com — YouTube\n"
        "  2. github.com — GitHub *\n"
        "  3. example.com — Example Domain"
    )
    spoken = _clean_tabs_for_speech(out)
    assert spoken == "3 tabs open: YouTube; GitHub, active; Example Domain."


def test_clean_tabs_empty() -> None:
    assert _clean_tabs_for_speech("") == "No open tabs."


def test_clean_tabs_falls_back_to_host_when_no_title() -> None:
    out = "1 tab open (* = active):\n  1. data.example.org — (no title) *"
    spoken = _clean_tabs_for_speech(out)
    assert spoken == "1 tab open: data.example.org, active."


def test_render_say_speaks_the_list_not_an_ack() -> None:
    spoken = say("browser_automation", "list_tabs", "ok", SAMPLE)
    assert "GitHub" in spoken and "blank tab" in spoken
    assert "active" in spoken


def test_assembler_primary_is_the_tab_list() -> None:
    primary, follow = responder.build(
        "browser_automation", "list_tabs", True,
        "Pulling up every open tab.",   # the generic brain ack — must be ignored
        SAMPLE, "",
    )
    assert "Pulling up every open tab" not in primary   # ack dropped
    assert "GitHub" in primary and "active" in primary  # real content spoken
    assert follow is None
