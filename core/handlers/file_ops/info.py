"""file_ops package — file/folder metadata (R2-17b split)."""

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

def _op_file_info(params, *, path, raw_path, confirmed):
    _tlog(f"❯ info {path.name}")
    if not path.exists():
        found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"✗ not found: {_resolved_missing_path(path)}")
            return _err(f"Not found: {_resolved_missing_path(path)}")

    try:
        st = path.stat()
    except OSError as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    try:
        full_path_str = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        full_path_str = str(path)

    try:
        mod_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, OverflowError):
        mod_str = "(unknown)"

    if path.is_dir():
        file_count = 0
        dir_count  = 0
        total_size = 0
        try:
            for root, dirs, files in os.walk(str(path)):
                dir_count += len(dirs)
                for name in files:
                    file_count += 1
                    try:
                        total_size += (Path(root) / name).stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        info_lines = [
            f"Folder:   {full_path_str}",
            f"Items:    {file_count + dir_count} ({dir_count} folder(s), {file_count} file(s))",
            f"Size:     {_format_human_size(total_size)} ({total_size:,} bytes total)",
            f"Modified: {mod_str}",
        ]
    else:
        ext = path.suffix.lower()
        label = _EXT_TYPE_HINTS.get(ext)
        if ext and label:
            type_str = f"{ext} — {label}"
        elif ext:
            type_str = ext
        else:
            type_str = "(no extension)"

        try:
            created_str = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            created_str = "(unknown)"

        if _is_probably_binary(path):
            line_count_line = "Lines:    (binary file)"
        else:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    nlines = sum(1 for _ in fh)
                line_count_line = f"Lines:    {nlines:,}"
            except Exception:
                line_count_line = "Lines:    (unreadable)"

        info_lines = [
            f"File:     {full_path_str}",
            f"Size:     {_format_human_size(st.st_size)} ({st.st_size:,} bytes)",
            f"Type:     {type_str}",
            f"Modified: {mod_str}",
            f"Created:  {created_str}",
            line_count_line,
        ]

    body = "\n".join(info_lines)
    _emit_to_terminal(body, command=f"info {path.name}")
    if path.is_dir():
        _tlog(f"✓ {_format_human_size(total_size)}, {file_count + dir_count} items, modified {mod_str}")
    else:
        line_summary = line_count_line.split(":", 1)[-1].strip() if ":" in line_count_line else "?"
        _tlog(f"✓ {_format_human_size(st.st_size)}, {line_summary} lines, modified {mod_str}")
    return _ok(body)
