"""file_ops package — in-file find/replace (R2-17b split)."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from core.handlers.shared import _ok, _err, _tlog, request_confirmation
from core.handlers.paths import _resolve_file_operation_path, _find_folder
from core.handlers.file_ops._common import (
    _BATCH_DELETE_MAX,
    _EXT_TYPE_HINTS,
    _FIND_LINE_MAX_LEN,
    _LIST_DIR_CAP,
    _READ_FILE_MAX_BYTES,
    _READ_FILE_OUTPUT_CAP,
    _REPLACE_PREVIEW_CTX,
    _SEARCH_PRUNE_DIRS,
    _SEARCH_RESULTS_CAP,
    _SEARCH_TIME_BUDGET_S,
    _emit_done,
    _emit_line,
    _emit_to_terminal,
    _find_existing_item,
    _format_human_size,
    _is_probably_binary,
    _is_redacted_placeholder,
    _locate_file,
    _parse_size_spec,
    _raw_path_is_bare_filename,
    _resolved_missing_path,
    _strip_llm_path_placeholders,
)

def _op_replace_in_file(params, *, path, raw_path, confirmed):
    _tlog(f"❯ replace in {path.name}")
    find_text    = params.get("find", "")
    replace_text = params.get("replace", "")
    try:
        count_arg = int(params.get("count", -1))
    except (TypeError, ValueError):
        count_arg = -1

    if not isinstance(find_text, str) or find_text == "":
        _tlog("✗ missing 'find' text to search for")
        return _err("Missing 'find' text to search for")
    if not isinstance(replace_text, str):
        _tlog("✗ missing 'replace' text")
        return _err("Missing 'replace' text")
    if _is_redacted_placeholder(replace_text):
        _tlog("✗ refusing to write a redacted placeholder as replacement text")
        return _err(
            "The replacement looks like a redacted placeholder ('<N chars>'), not real "
            "text — please re-issue the command."
        )

    if not path.exists():
        found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"✗ file not found: {_resolved_missing_path(path)}")
            return _err(f"File not found: {_resolved_missing_path(path)}")

    if _is_probably_binary(path):
        _tlog(f"✗ {path.name} looks like a binary file")
        return _err(
            f"{path.name} looks like a binary file — replace_in_file only supports text files."
        )

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _tlog(f"✗ {path.name} is not valid UTF-8")
        return _err(f"{path.name} is not valid UTF-8 text — refusing to edit.")
    except PermissionError:
        _tlog(f"✗ permission denied: {path.name}")
        return _err(f"Permission denied reading: {path.name}")
    except Exception as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    occurrences = content.count(find_text)
    if occurrences == 0:
        _tlog(f"✗ text not found in {path.name}")
        return _err(f"Text not found in {path.name}: {find_text!r}")

    # Preview the first match with ±50 chars of context.
    idx        = content.find(find_text)
    ctx_start  = max(0, idx - _REPLACE_PREVIEW_CTX)
    ctx_end    = min(len(content), idx + len(find_text) + _REPLACE_PREVIEW_CTX)
    before     = content[ctx_start:idx].replace("\n", "⏎")
    match_seg  = content[idx:idx + len(find_text)].replace("\n", "⏎")
    after      = content[idx + len(find_text):ctx_end].replace("\n", "⏎")
    prefix_ell = "…" if ctx_start > 0 else ""
    suffix_ell = "…" if ctx_end < len(content) else ""
    preview    = f"{prefix_ell}{before}[{match_seg}]{after}{suffix_ell}"

    count_label = "all" if count_arg < 0 else str(count_arg)
    prompt = (
        f"Replace in {path.name}?\n\n"
        f"Find:    {find_text!r}\n"
        f"Replace: {replace_text!r}\n"
        f"Occurrences: {occurrences} (will replace: {count_label})\n\n"
        f"Preview:\n{preview}"
    )

    captured_path    = path
    captured_find    = find_text
    captured_replace = replace_text
    captured_count   = count_arg
    captured_occ     = occurrences

    def _do_replace() -> dict:
        try:
            text_now = captured_path.read_text(encoding="utf-8")
            new_text = text_now.replace(captured_find, captured_replace, captured_count)
            applied  = text_now.count(captured_find) if captured_count < 0 else min(
                captured_count, text_now.count(captured_find)
            )
            captured_path.write_text(new_text, encoding="utf-8")
            msg = f"Replaced {applied} occurrence(s) in {captured_path.name}"
            _emit_to_terminal(
                f"── {captured_path.name}: replaced {applied} of {captured_occ} ──",
                command=f"replace {captured_find!r} → {captured_replace!r}",
            )
            _tlog(f"✓ {applied} replacement{'s' if applied != 1 else ''} saved")
            return _ok(msg)
        except PermissionError:
            _tlog(f"✗ permission denied: {captured_path.name}")
            return _err(f"Permission denied writing: {captured_path.name}")
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))

    _tlog("⚠ awaiting confirmation")
    return request_confirmation(prompt, _do_replace)
