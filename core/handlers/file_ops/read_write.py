"""file_ops package — read / append file-ops (R2-17b split)."""

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
    _is_redacted_placeholder,
    _format_human_size,
    _is_probably_binary,
    _locate_file,
    _parse_size_spec,
    _raw_path_is_bare_filename,
    _resolved_missing_path,
    _strip_llm_path_placeholders,
)

def _op_read_file(params, *, path, raw_path, confirmed):
    _tlog(f"❯ read {path.name}")

    # Optional line-range slicing. start_line is 1-indexed; end_line=-1 means EOF.
    try:
        start_line = max(1, int(params.get("start_line", 1)))
    except (TypeError, ValueError):
        start_line = 1
    try:
        end_line = int(params.get("end_line", -1))
    except (TypeError, ValueError):
        end_line = -1
    if end_line != -1 and end_line < start_line:
        _tlog(f"✗ end_line ({end_line}) must be >= start_line ({start_line})")
        return _err(f"end_line ({end_line}) must be >= start_line ({start_line})")

    if not path.exists():
        found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            result = _err(f"File not found: {_resolved_missing_path(path)}")
            _tlog(f"✗ {result['error']}")
            _emit_to_terminal(result["error"], success=False)
            return result

    try:
        size = path.stat().st_size
    except OSError as exc:
        result = _err(str(exc))
        _tlog(f"✗ {exc}")
        _emit_to_terminal(result["error"], success=False)
        return result

    if size > _READ_FILE_MAX_BYTES:
        _tlog(f"✗ file too large: {_format_human_size(size)}")
        return _err(
            f"File too large to read: {_format_human_size(size)} "
            f"(cap: {_format_human_size(_READ_FILE_MAX_BYTES)}) — "
            f"use start_line/end_line to read a slice."
        )

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        result = _err(f"Permission denied reading: {path.name}")
        _tlog(f"✗ permission denied: {path.name}")
        _emit_to_terminal(result["error"], success=False)
        return result
    except Exception as exc:
        result = _err(str(exc))
        _tlog(f"✗ {exc}")
        _emit_to_terminal(result["error"], success=False)
        return result

    all_lines = content.splitlines(keepends=True)
    total_lines = len(all_lines)

    sliced = (start_line != 1 or end_line != -1)
    if sliced:
        s_idx = start_line - 1
        e_idx = total_lines if end_line == -1 else min(end_line, total_lines)
        body = "".join(all_lines[s_idx:e_idx])
        shown_range = f"{s_idx + 1}-{e_idx}" if e_idx > s_idx else f"{s_idx + 1}"
    else:
        body = content
        shown_range = f"1-{total_lines}" if total_lines else "0"

    body_len = len(body)
    if body_len > _READ_FILE_OUTPUT_CAP:
        body_out = body[:_READ_FILE_OUTPUT_CAP] + (
            f"\n\n[truncated: showing {_READ_FILE_OUTPUT_CAP:,} of {body_len:,} chars "
            f"({total_lines:,} lines total) — use start_line/end_line to read specific sections]"
        )
    else:
        body_out = body

    cmd_label = f"read {path.name}" + (f" [{shown_range}]" if sliced else "")
    _emit_line(f"❯ {cmd_label}")
    _emit_line(f"── {path.name} ──")
    for line in body_out.splitlines():
        _emit_line(line)
    _emit_done(0)
    _tlog(f"✓ {path.name} — {total_lines:,} lines, {_format_human_size(size)}")
    return _ok(body_out)


def _op_append_file(params, *, path, raw_path, confirmed):
    _tlog(f"❯ append → {path.name}")
    content = params.get("content", "")
    if not isinstance(content, str) or content == "":
        _tlog("✗ missing 'content' to append")
        return _err("Missing 'content' to append")
    if _is_redacted_placeholder(content):
        _tlog("✗ refusing to append a redacted placeholder")
        return _err(
            "That content looks like a redacted placeholder ('<N chars>'), not real "
            "text — please re-issue the command."
        )
    use_timestamp = bool(params.get("timestamp", False))

    if not path.exists():
        found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"✗ file not found: {_resolved_missing_path(path)}")
            return _err(
                f"File not found: {_resolved_missing_path(path)} — use create_file to make a new one"
            )
    if path.is_dir():
        _tlog(f"✗ {path.name} is a directory")
        return _err(f"{path.name} is a directory — append_file only works on files")

    chunk = content
    if use_timestamp:
        chunk = datetime.now().strftime("[%Y-%m-%d %H:%M] ") + chunk
    if not chunk.endswith("\n"):
        chunk += "\n"

    # Pre-pend a leading newline if the file is non-empty and doesn't end in one,
    # so each append starts on its own line.
    try:
        with path.open("rb") as fh:
            try:
                fh.seek(-1, 2)
                last_byte = fh.read(1)
            except OSError:
                last_byte = b""
        if last_byte and last_byte != b"\n":
            chunk = "\n" + chunk
    except OSError:
        pass

    try:
        with path.open("a", encoding="utf-8") as fh:
            written = fh.write(chunk)
    except PermissionError:
        _tlog(f"✗ permission denied: {path.name}")
        return _err(f"Permission denied writing: {path.name}")
    except Exception as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    try:
        full_path_str = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        full_path_str = str(path)
    _emit_to_terminal(
        f"Appended {written} chars to {full_path_str}",
        command=f"append → {path.name}",
    )
    _tlog("✓ appended")
    return _ok(f"Appended {written} chars to {path.name}")
