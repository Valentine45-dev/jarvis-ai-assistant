"""file_ops package — create / mkdir file-ops (R2-17b split)."""

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

def _op_create_directory(params, *, path=None, raw_path="", confirmed=False):
    raw_path = params.get("path", "")
    s = (raw_path or "").strip()
    if not s:
        _tlog("✗ no path provided")
        return _err("No path provided")
    path = _strip_llm_path_placeholders(_resolve_file_operation_path(s))
    _tlog(f"❯ mkdir {path.name or s}")
    if path.exists() and path.is_file():
        _tlog(f"✗ that path is already a file: {path.name}")
        return _err(f"That path is already a file: {path.name}")
    try:
        target_display = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        target_display = str(path)
    prompt = (
        f"Create this folder? (Parent folders are created if needed.)\n\n"
        f"Folder: {target_display}"
    )

    def _do_mkdir() -> dict:
        try:
            path.mkdir(parents=True, exist_ok=True)
            _tlog(f"✓ created — {path.name}")
            return _ok(f"Created folder: {path.name}")
        except PermissionError:
            _tlog(f"✗ permission denied: {path}")
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))

    return request_confirmation(prompt, _do_mkdir)

def _op_create_file(params, *, path, raw_path, confirmed):
    path = _strip_llm_path_placeholders(path)
    content = params.get("content", "")
    # Data-loss backstop: the model occasionally copies a redacted `<N chars>`
    # placeholder from replayed history into `content` — refuse to write it.
    if _is_redacted_placeholder(content):
        _tlog("✗ refusing to write a redacted placeholder as file content")
        return _err(
            "That content looks like a redacted placeholder ('<N chars>'), not the "
            "real file content — please re-issue the command."
        )
    content_stripped = (content or "").strip() if isinstance(content, str) else ""
    raw_n = (raw_path or "").replace("\\", "/")
    has_trailing = len(raw_n) > 0 and raw_n.rstrip().endswith("/")

    if not path.suffix and not has_trailing and not content_stripped:
        # Falls through to create_directory which emits its own ❯/✓/✗.
        return _op_create_directory({"path": str(path), **{k: v for k, v in params.items() if k != "path"}})

    if not path.suffix:
        path = path / "jarvis_note.txt"

    _tlog(f"❯ create {path.name}")

    parent = path.parent
    try:
        target_display = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        target_display = str(path)
    try:
        folder_display = str(parent.resolve())
    except (OSError, ValueError, RuntimeError):
        folder_display = str(parent)

    lines = [f"File:  {target_display}", f"Folder: {folder_display}"]
    if not parent.exists():
        lines.append(
            "Note: that folder is not on disk yet — I can create it when you confirm."
        )
    path_summary = "\n".join(lines)

    captured_path = path
    captured_parent = parent

    def _do_create() -> dict:
        try:
            if not captured_parent.exists():
                captured_parent.mkdir(parents=True, exist_ok=True)
            captured_path.write_text(content, encoding="utf-8")
            try:
                size = _format_human_size(captured_path.stat().st_size)
            except OSError:
                size = "?"
            _tlog(f"✓ created — {captured_path.name} ({size})")
            return _ok(f"Created: {captured_path.name}")
        except PermissionError:
            _tlog(f"✗ permission denied: {captured_path}")
            return _err(f"Permission denied: {captured_path}")
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))

    from core.personality import ask as _ask
    _tlog(f"⚠ awaiting confirmation — {target_display}")
    return request_confirmation(_ask("create_file", path_summary), _do_create)
