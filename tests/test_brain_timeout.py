"""Brain API timeout — split per-operation timeout scaled to the output budget.

The brain call is NON-streaming, so on a large generation (e.g. a ~5k-char
create_file) the entire body arrives only after the model finishes — no bytes flow
meanwhile, so httpx's READ timeout behaves like a total generation deadline. A flat
15 s cut those off mid-write and surfaced the `api_timeout` fallback even though the
brain was reachable.

Fix (core/brain.py): `_api_timeout_for(max_out)` keeps connect/write/pool short
(~10 s, so a dead network still fails fast) and scales the READ timeout off the SAME
`_infer_max_output_tokens` budget that already sizes `max_tokens` — one signal, no
parallel heuristic. The big-content path also caps SDK retries (no 3× regeneration).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import core.brain as brain
from core.brain import _api_timeout_for, ask_claude

# A model reply the brain can parse — the intent itself doesn't matter for these
# tests; we're verifying the timeout/retry wiring around the call.
_VALID = (
    '{"intent":"code_execution","action":"create_file","parameters":{},'
    '"confidence":0.9,"response":"ok","hud_status":"FILE OPS",'
    '"requires_confirmation":false}'
)

# Prompt that trips the 16384 budget ("python script" code-phrase + "write " verb)
# while NOT matching the deterministic file-creation fast-path (no "create a file"
# phrasing), so it actually reaches the model call.
_BIG_PROMPT = (
    "write a python script that implements a mini file search engine "
    "with recursive indexing and ranking"
)


def _reply(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


# ── pure function: read scales, connect stays short ─────────────────────────


def test_read_scales_with_budget():
    assert _api_timeout_for(2048).read == 20.0
    assert _api_timeout_for(8192).read == 60.0
    assert _api_timeout_for(16384).read == 90.0


def test_connect_stays_short_regardless_of_read():
    # Non-negotiable: connect (and write/pool) stay ~10 s at every budget, so a
    # genuinely dead network fast-fails even when the read budget is the full 90 s.
    for mx in (2048, 8192, 16384):
        t = _api_timeout_for(mx)
        assert t.connect == 10.0
        assert t.write == 10.0
        assert t.pool == 10.0
    big = _api_timeout_for(16384)
    assert big.connect == 10.0 and big.read == 90.0


# ── integration: wiring into ask_claude ─────────────────────────────────────


@pytest.fixture
def brain_client(mock_anthropic, monkeypatch):
    """Anthropic mock wired for ask_claude timeout/retry assertions.

    `with_options` returns the same mock so both the cap call and the eventual
    `messages.create` are observable in one place. Response-memory IO is stubbed
    so the test stays hermetic (no data/ file writes).
    """
    mock_anthropic.with_options.return_value = mock_anthropic
    mock_anthropic.messages.create.return_value = _reply(_VALID)

    import core.response_memory as rm
    monkeypatch.setattr(rm, "format_block", lambda *a, **k: "", raising=False)
    monkeypatch.setattr(rm, "record", lambda *a, **k: None, raising=False)
    return mock_anthropic


def test_big_generation_gets_long_read_and_caps_retries(brain_client):
    # The exact repro shape: a large generation completes instead of api_timeout.
    r = ask_claude(_BIG_PROMPT, use_memory=False)
    assert r.get("_error") != "api_timeout"
    assert r["intent"] != "unknown"

    # Retry cap is SCOPED to the big path (one shot — no 3× regeneration).
    brain_client.with_options.assert_called_with(max_retries=0)

    # Read scaled to the budget; connect still short.
    t = brain_client.messages.create.call_args.kwargs["timeout"]
    assert t.read == 90.0
    assert t.connect == 10.0


def test_short_command_keeps_snappy_ceiling_and_default_retries(brain_client):
    r = ask_claude("what time is it", use_memory=False)
    assert r.get("_error") is None

    # No retry cap on the fast path — a transient timeout there is cheap to retry.
    brain_client.with_options.assert_not_called()

    t = brain_client.messages.create.call_args.kwargs["timeout"]
    assert t.read == 20.0
    assert t.connect == 10.0


def test_api_timeout_still_surfaces_fallback(brain_client):
    import anthropic
    brain_client.messages.create.side_effect = anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )
    r = ask_claude(_BIG_PROMPT, use_memory=False)
    assert r["intent"] == "unknown"
    assert r["_error"] == "api_timeout"
    assert r["hud_status"] == "TIMEOUT"


def test_529_retry_uses_scaled_timeout_at_both_sites(brain_client, monkeypatch):
    # A 529 mid-big-generation must NOT fall back to the old 15 s on retry — both
    # the primary call and the manual 529-retry block use the scaled timeout.
    import time

    import anthropic

    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    resp = httpx.Response(529, request=httpx.Request("POST", "https://api.anthropic.com"))
    err = anthropic.APIStatusError("overloaded", response=resp, body=None)
    brain_client.messages.create.side_effect = [err, _reply(_VALID)]

    r = ask_claude(_BIG_PROMPT, use_memory=False)
    assert r.get("_error") != "api_error_529"
    assert r["intent"] != "unknown"
    assert brain_client.messages.create.call_count == 2
    for call in brain_client.messages.create.call_args_list:
        t = call.kwargs["timeout"]
        assert t.read == 90.0
        assert t.connect == 10.0
