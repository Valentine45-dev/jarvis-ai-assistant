"""R3-13: conversation memory must redact dictated secrets before they hit disk.

The model's JSON echoes content/text/value/code parameters — dictated file
bodies, passwords, API keys, code. Those must not persist to data/memory.jsonl
in plaintext nor reload into the prompt. Redaction reuses brain._redact_params
(content/text/value/code, >24 chars → "<N chars>"); the free-form user command
text is intentionally left alone (params-only, by design).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

import core.memory as memory


def _assistant(content_val: str) -> str:
    return json.dumps({
        "intent": "file_operation",
        "action": "create_file",
        "parameters": {"path": "secret.txt", "content": content_val},
    })


@pytest.fixture
def mem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[memory.ConversationMemory]:
    monkeypatch.setattr(memory, "_PERSIST_PATH", tmp_path / "memory.jsonl")
    yield memory.ConversationMemory(max_tokens=100_000)


def test_long_secret_content_redacted(mem: memory.ConversationMemory) -> None:
    secret = "hunter2-" * 10                       # > 24 chars
    mem.add_exchange("create a file with my password", _assistant(secret))
    user, asst = mem.get_messages()
    assert secret not in asst["content"]
    assert "chars>" in asst["content"]             # length-prefixed redaction
    # Params-only: the user's command text is preserved verbatim.
    assert user["content"] == "create a file with my password"


def test_short_content_preserved(mem: memory.ConversationMemory) -> None:
    mem.add_exchange("x", _assistant("hi"))         # < 24 chars → not redacted
    assert '"hi"' in mem.get_messages()[1]["content"]


def test_persisted_file_is_redacted(mem: memory.ConversationMemory) -> None:
    secret = "sk-" + "a" * 60
    mem.add_exchange("type my api key", _assistant(secret))
    disk = memory._PERSIST_PATH.read_text(encoding="utf-8")
    assert secret not in disk
    assert "chars>" in disk


def test_non_json_assistant_stored_unchanged(mem: memory.ConversationMemory) -> None:
    mem.add_exchange("hello", "just a plain response, not json")
    assert mem.get_messages()[1]["content"] == "just a plain response, not json"


def test_non_secret_params_preserved(mem: memory.ConversationMemory) -> None:
    asst = json.dumps({"intent": "open_app", "action": "open_browser",
                       "parameters": {"browser": "chrome"}})
    mem.add_exchange("open chrome", asst)
    assert '"browser": "chrome"' in mem.get_messages()[1]["content"]


# ── prompt-facing replay drops the placeholder (data-loss root-cause fix) ────
# Privacy redaction stores `<N chars>` (disk + in-memory). But replaying that to the
# model let it COPY the placeholder into a new create_file's content → `<N chars>`
# written to disk. get_prompt_messages() drops the redacted key for the model only;
# get_messages()/disk keep `<N chars>`.

def test_prompt_messages_drops_redacted_content_key(mem: memory.ConversationMemory) -> None:
    secret = "x" * 200
    mem.add_exchange("write a big file", _assistant(secret))

    stored = mem.get_messages()[1]["content"]
    prompt = mem.get_prompt_messages()[1]["content"]

    # Stored form keeps the placeholder (privacy/R3-13 unchanged)…
    assert "chars>" in stored
    # …but the model-facing form has NO placeholder to copy, and drops the key.
    assert "chars>" not in prompt
    obj = json.loads(prompt)
    assert "content" not in obj["parameters"]       # key dropped, not replaced
    assert obj["parameters"]["path"] == "secret.txt"  # other params kept
    assert obj["action"] == "create_file"


def test_prompt_messages_non_secret_params_preserved(mem: memory.ConversationMemory) -> None:
    asst = json.dumps({"intent": "open_app", "action": "open_browser",
                       "parameters": {"browser": "chrome"}})
    mem.add_exchange("open chrome", asst)
    prompt = mem.get_prompt_messages()[1]["content"]
    assert '"browser": "chrome"' in prompt           # nothing redacted → untouched


def test_prompt_messages_handles_result_suffix(mem: memory.ConversationMemory) -> None:
    # inject_outcome appends a "\n[Result: …]" suffix to the last assistant turn —
    # get_prompt_messages must strip the placeholder WITHOUT choking on the suffix.
    mem.add_exchange("write a big file", _assistant("y" * 200))
    mem.inject_outcome("file_operation", "create_file", success=True, output="Created: secret.txt")

    prompt = mem.get_prompt_messages()[1]["content"]
    assert "[Result:" in prompt                      # suffix preserved
    assert "chars>" not in prompt                    # placeholder still dropped
    json_part = prompt.split("\n[Result:", 1)[0]
    assert "content" not in json.loads(json_part)["parameters"]


def test_prompt_messages_failsoft_on_non_json(mem: memory.ConversationMemory) -> None:
    mem.add_exchange("hello", "just a plain response, not json")
    # Non-JSON assistant turn is returned unchanged (never dropped/corrupted).
    assert mem.get_prompt_messages()[1]["content"] == "just a plain response, not json"


def test_load_redacts_legacy_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "memory.jsonl"
    secret = "p@ssw0rd-very-long-secret-value-here"
    path.write_text(
        json.dumps({"role": "user", "content": "create file"}) + "\n"
        + json.dumps({"role": "assistant", "content": _assistant(secret)}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(memory, "_PERSIST_PATH", path)
    mem = memory.ConversationMemory(max_tokens=100_000)
    asst = mem.get_messages()[1]["content"]
    assert secret not in asst                        # legacy plaintext scrubbed on load
    assert "chars>" in asst
