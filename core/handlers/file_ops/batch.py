"""file_ops package — batch (glob) delete (R2-17b split)."""

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

def _op_batch_delete(params, *, path, raw_path, confirmed):
    glob_pat  = (params.get("pattern") or "").strip()
    recursive = bool(params.get("recursive", False))

    if not glob_pat:
        _tlog("✗ missing 'pattern' (glob, e.g. '*.tmp')")
        return _err("Missing 'pattern' (glob, e.g. '*.tmp')")

    if not path.exists():
        found_dir = _find_folder(raw_path) if raw_path else None
        if found_dir:
            path = found_dir
        else:
            _tlog(f"❯ batch delete {glob_pat!r} in {raw_path or path.name}")
            _tlog(f"✗ directory not found: {raw_path or path}")
            return _err(f"Directory not found: {raw_path or path}")
    if not path.is_dir():
        _tlog(f"❯ batch delete {glob_pat!r} in {path.name}")
        _tlog(f"✗ not a directory: {path}")
        return _err(f"Not a directory: {path}")

    _tlog(f"❯ batch delete {glob_pat!r} in {path.name}")

    # Files only — globs match dirs too, and we never want to unlink() a folder.
    candidates: list[Path] = []
    try:
        if recursive:
            for root, dirs, files in os.walk(str(path), topdown=True):
                dirs[:] = [d for d in dirs if d.lower() not in _SEARCH_PRUNE_DIRS]
                for name in files:
                    if fnmatch.fnmatch(name, glob_pat):
                        candidates.append(Path(root) / name)
                        if len(candidates) > _BATCH_DELETE_MAX:
                            break
                if len(candidates) > _BATCH_DELETE_MAX:
                    break
        else:
            for p in path.glob(glob_pat):
                if p.is_file():
                    candidates.append(p)
                    if len(candidates) > _BATCH_DELETE_MAX:
                        break
    except PermissionError:
        _tlog(f"✗ permission denied scanning: {path}")
        return _err(f"Permission denied scanning: {path}")
    except Exception as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    if not candidates:
        _tlog(f"✓ 0 files matched {glob_pat!r}")
        return _ok(f"No files matched {glob_pat!r} in {path.name}/")

    if len(candidates) > _BATCH_DELETE_MAX:
        _tlog(f"✗ too many matches (>{_BATCH_DELETE_MAX})")
        return _err(
            f"Too many matches (>{_BATCH_DELETE_MAX}) for {glob_pat!r} — narrow your pattern."
        )

    total_size = 0
    for p in candidates:
        try:
            total_size += p.stat().st_size
        except OSError:
            pass

    preview_lines = [f"  {p}" for p in candidates]

    prompt = (
        f"Delete these files?\n\n"
        f"Pattern:  {glob_pat}\n"
        f"Location: {path}\n"
        f"Recursive: {recursive}\n\n"
        f"Files to delete:\n" + "\n".join(preview_lines) + "\n\n"
        f"Total: {len(candidates)} file(s), {_format_human_size(total_size)}"
    )

    captured_files = list(candidates)
    captured_total = total_size
    captured_label = f"batch_delete {glob_pat!r} in {path}"

    def _do_batch_delete() -> dict:
        deleted     = 0
        freed_bytes = 0
        errors: list[str] = []
        _emit_line(f"❯ {captured_label}")
        for fp in captured_files:
            try:
                sz = fp.stat().st_size
            except OSError:
                sz = 0
            try:
                fp.unlink()
                deleted += 1
                freed_bytes += sz
                _emit_line(f"Deleted: {fp}")
            except Exception as exc:
                errors.append(f"{fp.name}: {exc}")
                _emit_line(f"Failed:  {fp} — {exc}")
        _emit_done(0 if not errors else 1)

        base_msg = f"Deleted {deleted} file(s), freed {_format_human_size(freed_bytes)}"
        if errors:
            err_tail = "; ".join(errors[:3])
            if len(errors) > 3:
                err_tail += f"; +{len(errors) - 3} more"
            _tlog(f"✗ {len(errors)} file(s) could not be deleted (deleted {deleted})")
            return {
                "success": deleted > 0,
                "output":  f"{base_msg}. {len(errors)} failed: {err_tail}",
                "error":   f"{len(errors)} file(s) could not be deleted",
            }
        _tlog(f"✓ deleted {deleted} file{'s' if deleted != 1 else ''}")
        return _ok(base_msg)

    _tlog(f"⚠ awaiting confirmation — {len(candidates)} files")
    return request_confirmation(prompt, _do_batch_delete)
