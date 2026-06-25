"""Opt-in explicit-content gate for web searches (controller, not a filter).

JARVIS never REFUSES a search — that would break the "controller, not a safety
filter" ethos in CLAUDE.md. But when ``config.safe_search_confirm`` is ON (default
OFF), an explicit/adult query gets a confirmation card *first*, so a shared or
family machine doesn't surface NSFW results on a misheard or careless command. The
user opts in; the gate only adds a speed-bump, it never blocks.

Detection is deliberately conservative: a missed term is better than a false
positive nagging a normal search. Single words are word-boundary matched (so "sex"
in "Essex", "anal" in "analysis", "cum" in "cumulative" don't trip it), and the
most ambiguous singles (nude/naked/escort/sex) are intentionally LEFT OUT — they
appear in plenty of innocent queries ("nude lipstick", "naked mole rat", "sex
education"). Unambiguous multi-word phrases are matched as substrings instead.
"""

from __future__ import annotations

import re

# Single tokens that are overwhelmingly explicit on their own. Word-boundary
# matched (case-insensitive) via the tokenizer below.
_EXPLICIT_TERMS: frozenset[str] = frozenset({
    "porn", "porno", "pornography", "pornhub", "xvideos", "xnxx", "xhamster",
    "redtube", "youporn", "onlyfans", "rule34", "hentai", "nsfw", "xxx",
    "nudes", "boobs", "tits", "blowjob", "handjob", "creampie", "deepthroat",
    "milf", "gangbang", "bukkake", "camgirl", "sextape", "dildo", "bdsm",
})

# Unambiguous multi-word phrases — specific enough to match as plain substrings.
_EXPLICIT_PHRASES: tuple[str, ...] = (
    "sex tape", "porn movie", "porn movies", "porn video", "porn videos",
    "adult video", "adult movie", "nude pics", "naked pics", "sex video",
    "sex videos", "nude photos",
)

_WORD_RE = re.compile(r"[a-z0-9']+")


def is_explicit_query(query: str) -> bool:
    """True when *query* contains an explicit phrase (substring) or term (word).

    Used only when the user has opted into the gate; a True result triggers a
    confirmation card, never a refusal.
    """
    if not query:
        return False
    low = query.lower()
    if any(phrase in low for phrase in _EXPLICIT_PHRASES):
        return True
    tokens = set(_WORD_RE.findall(low))
    return bool(tokens & _EXPLICIT_TERMS)
