"""file_ops package — single-file delete (R2-17b split)."""

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
    _locate_file,
    _parse_size_spec,
    _raw_path_is_bare_filename,
    _resolved_missing_path,
    _strip_llm_path_placeholders,
)

def _op_delete_file(params, *, path, raw_path, confirmed):
    _tlog(f"❯ delete {path.name}")
    if not path.exists():
        found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"✗ cannot find {_resolved_missing_path(path)!r}")
            return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")
    try:
        full_path_str = str(path.resolve())
    except (OSError, ValueError):
        full_path_str = str(path)
    is_dir = path.is_dir()
    kind   = "Folder" if is_dir else "File"
    lines  = [f"{kind}: {full_path_str}"]
    try:
        size_label = _format_human_size(path.stat().st_size) if not is_dir else "folder"
    except OSError:
        size_label = "?"
    if is_dir:
        try:
            n = sum(1 for _ in path.rglob("*"))
            lines.append(f"Contains: {n} item(s) — all will be permanently removed")
        except (PermissionError, OSError):
            lines.append("Note: all contents will be permanently removed")
    item_desc = "\n".join(lines)

    captured_path = path
    captured_name = path.name

    def _do_delete() -> dict:
        try:
            if captured_path.is_dir():
                shutil.rmtree(captured_path)
            else:
                captured_path.unlink()
            _tlog(f"✓ deleted — {captured_name}")
            return _ok(f"Deleted: {captured_name}")
        except PermissionError:
            msg = f"Permission denied: {captured_name}"
            _tlog(f"✗ {msg}")
            return {"success": False, "output": msg, "error": msg}
        except Exception as exc:
            msg = str(exc)
            _tlog(f"✗ {msg}")
            return {"success": False, "output": msg, "error": msg}

    from core.personality import ask as _ask
    if confirmed:
        return _do_delete()
    _tlog(f"⚠ awaiting confirmation — {captured_name} ({size_label})")
    return request_confirmation(_ask("delete_file", item_desc), _do_delete)
