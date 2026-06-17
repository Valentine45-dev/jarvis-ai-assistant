"""first_sentence() must preserve inline audio tags.

Regression for the live bug where ElevenLabs v3 audio tags ([laughs]/[sighs]/…)
never rendered: the brain emitted them, but first_sentence() truncated any
response over its 150-char cap at the first sentence boundary — and JARVIS puts
the tag just before the punchline, i.e. in the discarded tail. So the tag was
stripped before it ever reached the TTS provider. Tagged responses must survive
first_sentence intact; untagged responses keep the old truncation behaviour.
"""

from __future__ import annotations

from core.responders.assembler import responder
from core.responders.utils import first_sentence

# A real >150-char multi-sentence joke with the tag after the first sentence.
TAGGED_JOKE = (
    "America is so obsessed with speed they invented fast food, fast lanes, and "
    "fast fashion, then wondered why everything feels empty. [laughs softly] "
    "Land of the free, home of the two-day shipping."
)


def test_tagged_long_response_survives_intact():
    assert len(TAGGED_JOKE) > 150
    out = first_sentence(TAGGED_JOKE)
    assert out == TAGGED_JOKE                 # not truncated at all
    assert "[laughs softly]" in out           # the tag reaches TTS


def test_untagged_long_response_still_truncates():
    long_plain = (
        "America is so obsessed with speed they invented fast food, fast lanes, "
        "and fast fashion, then wondered why everything feels empty. Land of the "
        "free, home of the two-day shipping."
    )
    assert len(long_plain) > 150
    out = first_sentence(long_plain)
    assert out.endswith("feels empty.")       # unchanged brevity behaviour
    assert len(out) < len(long_plain)


def test_short_response_unchanged():
    s = "Chrome's up. [laughs] Enjoy."
    assert first_sentence(s) == s


def test_tag_only_short_line_unchanged():
    assert first_sentence("[sighs] Fine, rebooting.") == "[sighs] Fine, rebooting."


def test_assembler_keeps_tag_for_joke():
    # End-to-end through the spoken-response builder used by the live pipeline.
    primary, _ = responder.build("jarvis_meta", "tell_joke", True, TAGGED_JOKE)
    assert "[laughs softly]" in primary
