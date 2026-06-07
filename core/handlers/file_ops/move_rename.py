"""file_ops package — rename / move / copy file-ops (R2-17b split)."""

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

def _op_rename_file(params, *, path, raw_path, confirmed):
    if not path.exists():
        found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"❯ rename {path.name}")
            _tlog(f"✗ cannot find {_resolved_missing_path(path)!r}")
            return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")
    new_name_raw = (params.get("new_name") or params.get("destination") or "").strip()
    if not new_name_raw:
        _tlog(f"❯ rename {path.name}")
        _tlog("✗ no new name provided")
        return _err("No new name provided for rename.")
    new_filename = Path(new_name_raw).name or new_name_raw
    dest_path    = path.parent / new_filename
    _tlog(f"❯ rename {path.name} → {new_filename}")
    try:
        loc_str = str(path.parent.resolve())
    except (OSError, ValueError):
        loc_str = str(path.parent)
    rename_desc = f"From: {path.name}\nTo:   {new_filename}\nIn:   {loc_str}"

    captured_path = path
    captured_dest = dest_path
    captured_new = new_filename

    def _do_rename() -> dict:
        try:
            if captured_dest.exists():
                msg = f"'{captured_new}' already exists in that location"
                _tlog(f"✗ {msg}")
                return {"success": False, "output": msg, "error": msg}
            captured_path.rename(captured_dest)
            _tlog("✓ renamed")
            return _ok(f"Renamed to {captured_new}")
        except PermissionError:
            msg = "Permission denied"
            _tlog(f"✗ {msg}")
            return {"success": False, "output": msg, "error": msg}
        except Exception as exc:
            msg = str(exc)
            _tlog(f"✗ {msg}")
            return {"success": False, "output": msg, "error": msg}

    from core.personality import ask as _ask
    _tlog("⚠ awaiting confirmation")
    return request_confirmation(_ask("rename_file", rename_desc), _do_rename)


def _op_move_file(params, *, path, raw_path, confirmed):
    if not path.exists():
        found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
        if found:
            path = found
        else:
            _tlog(f"❯ move {path.name}")
            _tlog(f"✗ cannot find {_resolved_missing_path(path)!r}")
            return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")

    # Resolve destination once, here, so the flow is readable:
    # single-segment ("desktop") goes through the shortcut/fuzzy matcher;
    # anything else goes through the standard file-operation resolver.
    raw_dest_str = (params.get("destination") or "").strip()
    if not raw_dest_str:
        _tlog(f"❯ move {path.name}")
        _tlog("✗ no destination provided")
        return _err("No destination provided")
    if "/" not in raw_dest_str and "\\" not in raw_dest_str:
        cleaned_dest = raw_dest_str
        lc = cleaned_dest.lower()
        for suffix in (" folder", " directory", " dir"):
            if lc.endswith(suffix):
                cleaned_dest = cleaned_dest[: -len(suffix)].strip()
                break
        lookup = cleaned_dest or raw_dest_str
        found_folder = _find_folder(lookup)
        dest = found_folder if found_folder else (path.parent / lookup)
    else:
        dest = _resolve_file_operation_path(raw_dest_str)

    # shutil.move drops the source into `dest` when `dest` is an existing dir.
    final_path = (dest / path.name) if (dest.exists() and dest.is_dir()) else dest

    try:
        from_display = str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        from_display = str(path)
    try:
        to_display = str(final_path.resolve()) if final_path.exists() else str(final_path)
    except (OSError, ValueError, RuntimeError):
        to_display = str(final_path)

    lines = [f"From: {from_display}", f"To:   {to_display}"]
    if final_path.exists():
        lines.append(f"Warning: {final_path.name} already exists at destination")
    move_desc = "Move this?\n\n" + "\n".join(lines)

    captured_path  = path
    captured_dest  = dest
    captured_final = final_path

    _tlog(f"❯ move {captured_path.name} → {captured_dest.name or captured_dest}")

    def _do_move() -> dict:
        try:
            shutil.move(str(captured_path), str(captured_dest))
            _tlog("✓ moved")
            return _ok(f"Moved {captured_path.name} → {captured_final}")
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))

    return request_confirmation(move_desc, _do_move)


def _op_copy_file(params, *, path, raw_path, confirmed):
    raw_dest_str = (params.get("destination") or "").strip()
    if not raw_dest_str:
        _tlog(f"❯ copy {path.name}")
        _tlog("✗ no destination provided")
        return _err("No destination provided")
    dest = _resolve_file_operation_path(raw_dest_str)
    _tlog(f"❯ copy {path.name} → {dest.name or dest}")
    try:
        shutil.copy2(str(path), str(dest))
        _tlog("✓ copied")
        return _ok(f"Copied {path.name}")
    except Exception as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))
