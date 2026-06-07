"""file_ops package — list / search-by-name / grep-contents file-ops (R2-17b split)."""

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

def _op_list_directory(params, *, path, raw_path, confirmed):
    sort_by = (params.get("sort") or "name").strip().lower()
    if sort_by not in ("name", "date", "size", "type"):
        sort_by = "name"
    glob_pat = (params.get("pattern") or "").strip()

    if not path.exists():
        found_dir = _find_folder(raw_path) if raw_path else None
        if found_dir:
            path = found_dir
        else:
            result = _err(f"Directory not found: {raw_path or path}")
            _emit_to_terminal(result["error"], success=False)
            return result

    try:
        entries = list(path.glob(glob_pat)) if glob_pat else list(path.iterdir())
    except PermissionError:
        result = _err(f"Permission denied: {path}")
        _emit_to_terminal(result["error"], success=False)
        return result
    except Exception as exc:
        result = _err(str(exc))
        _emit_to_terminal(result["error"], success=False)
        return result

    def _stat_or_zero(p: Path, attr: str) -> float:
        try:
            return float(getattr(p.stat(), attr))
        except OSError:
            return 0.0

    if sort_by == "date":
        entries.sort(key=lambda p: _stat_or_zero(p, "st_mtime"), reverse=True)
    elif sort_by == "size":
        entries.sort(key=lambda p: (_stat_or_zero(p, "st_size") if p.is_file() else 0), reverse=True)
    elif sort_by == "type":
        entries.sort(key=lambda p: (p.is_file(), p.name.lower()))
    else:  # name (default)
        entries.sort(key=lambda p: p.name.lower())

    total   = len(entries)
    n_dirs  = sum(1 for p in entries if p.is_dir())
    n_files = total - n_dirs
    shown   = entries[:_LIST_DIR_CAP]

    label = (path.name or str(path)) + "/"
    pat_suffix = f" matching {glob_pat!r}" if glob_pat else ""
    header = f"{label}{pat_suffix} — {total} item(s) ({n_dirs} folder(s), {n_files} file(s)):"

    lines = [header]
    for p in shown:
        icon = "[DIR] " if p.is_dir() else "[FILE]"
        lines.append(f"{icon} {p.name}")
    if total > _LIST_DIR_CAP:
        lines.append(f"[truncated: showing {_LIST_DIR_CAP} of {total} items]")

    body = "\n".join(lines)
    _emit_to_terminal(body, command=f"ls {path}" + (f" {glob_pat}" if glob_pat else ""))
    return _ok(body)


def _op_search_files(params, *, path, raw_path, confirmed):
    pattern         = params.get("pattern") or "*"
    modified_after  = params.get("modified_after")
    size_gt_raw     = params.get("size_gt")
    size_lt_raw     = params.get("size_lt")
    if not raw_path:
        base = Path.home()
    elif path.exists() and path.is_dir():
        base = path
    elif path.exists():
        _tlog(f"❯ search files {pattern!r} in {path.name}")
        _tlog(f"✗ not a directory: {path}")
        return _err(f"Not a directory: {path}")
    else:
        found_dir = _find_folder(raw_path)
        if found_dir:
            base = found_dir
        else:
            _tlog(f"❯ search files {pattern!r} in {raw_path or path.name}")
            _tlog(f"✗ directory not found: {_resolved_missing_path(path)}")
            return _err(f"Directory not found: {_resolved_missing_path(path)}")

    _tlog(f"❯ search files {pattern!r} in {base.name or base}")

    # Parse filters up-front so bad input fails fast with a helpful message.
    after_ts: float | None = None
    if modified_after:
        try:
            after_ts = datetime.strptime(str(modified_after).strip(), "%Y-%m-%d").timestamp()
        except (ValueError, TypeError):
            _tlog("✗ invalid modified_after — use YYYY-MM-DD")
            return _err("Invalid modified_after — use YYYY-MM-DD")

    size_gt = _parse_size_spec(size_gt_raw) if size_gt_raw is not None else None
    if size_gt_raw is not None and size_gt is None:
        _tlog("✗ invalid size_gt — use e.g. '1MB', '500KB'")
        return _err("Invalid size_gt — use e.g. '1MB', '500KB'")
    size_lt = _parse_size_spec(size_lt_raw) if size_lt_raw is not None else None
    if size_lt_raw is not None and size_lt is None:
        _tlog("✗ invalid size_lt — use e.g. '1MB', '500KB'")
        return _err("Invalid size_lt — use e.g. '1MB', '500KB'")

    deadline = time.monotonic() + _SEARCH_TIME_BUDGET_S
    matches: list[Path] = []
    truncated_reason: str | None = None

    try:
        for root, dirs, files in os.walk(str(base), topdown=True):
            if time.monotonic() > deadline:
                truncated_reason = f"time budget ({int(_SEARCH_TIME_BUDGET_S)}s) exceeded"
                break
            dirs[:] = [d for d in dirs if d.lower() not in _SEARCH_PRUNE_DIRS]
            for name in files:
                if not fnmatch.fnmatch(name, pattern):
                    continue
                p = Path(root) / name
                try:
                    st = p.stat()
                except OSError:
                    continue
                if after_ts is not None and st.st_mtime < after_ts:
                    continue
                if size_gt is not None and st.st_size <= size_gt:
                    continue
                if size_lt is not None and st.st_size >= size_lt:
                    continue
                matches.append(p)
                if len(matches) >= _SEARCH_RESULTS_CAP:
                    truncated_reason = f"result cap ({_SEARCH_RESULTS_CAP})"
                    break
            if truncated_reason:
                break
    except Exception as exc:
        result = _err(str(exc))
        _tlog(f"✗ {exc}")
        _emit_to_terminal(result["error"], success=False)
        return result

    cmd_label = f"find '{pattern}' in {base.name}/"
    if not matches:
        _tlog("✗ nothing found")
        _emit_to_terminal("No matching files found.", command=cmd_label)
        return _ok("No matching files found.")

    lines  = [f"[FILE] {p}" for p in matches]
    header = f"── {len(lines)} result(s) for '{pattern}' in {base.name}/ ──"
    body_lines = [header, *lines]
    if truncated_reason:
        body_lines.append(f"[partial: {truncated_reason}]")

    _tlog(f"✓ {len(matches)} file{'s' if len(matches) != 1 else ''} found")
    _emit_to_terminal("\n".join(body_lines), command=cmd_label)
    return _ok("\n".join(p.name for p in matches))


def _op_find_in_files(params, *, path, raw_path, confirmed):
    pattern_raw = params.get("pattern", "")
    if not isinstance(pattern_raw, str) or pattern_raw == "":
        _tlog("✗ missing 'pattern' (content to search for)")
        return _err("Missing 'pattern' (content to search for)")

    glob_pat       = (params.get("glob") or "").strip()
    use_regex      = bool(params.get("regex", False))
    case_sensitive = bool(params.get("case_sensitive", False))

    # Decision A: default to Path.cwd() when no path provided.
    if not raw_path:
        base = Path.cwd()
    elif path.exists():
        base = path
    else:
        found_dir = _find_folder(raw_path)
        if found_dir:
            base = found_dir
        else:
            _tlog(f"✗ path not found: {raw_path}")
            return _err(f"Path not found: {raw_path}")

    flags = 0 if case_sensitive else re.IGNORECASE
    if use_regex:
        try:
            matcher = re.compile(pattern_raw, flags)
        except re.error as exc:
            _tlog(f"✗ invalid regex: {exc}")
            return _err(f"Invalid regex: {exc}")
    else:
        matcher = re.compile(re.escape(pattern_raw), flags)

    def _iter_files():
        if base.is_file():
            yield base
            return
        for root, dirs, files in os.walk(str(base), topdown=True):
            dirs[:] = [d for d in dirs if d.lower() not in _SEARCH_PRUNE_DIRS]
            for name in files:
                if glob_pat and not fnmatch.fnmatch(name, glob_pat):
                    continue
                yield Path(root) / name

    cmd_label = (
        f"grep {pattern_raw!r} in {base.name or base}/"
        + (f" --glob {glob_pat}" if glob_pat else "")
        + (" --regex" if use_regex else "")
    )
    _emit_line(f"❯ {cmd_label}")

    deadline       = time.monotonic() + _SEARCH_TIME_BUDGET_S
    matches: list[tuple[Path, int]] = []
    files_with_matches: set[Path]   = set()
    files_skipped_binary = 0
    truncated_reason: str | None = None

    try:
        for fp in _iter_files():
            if time.monotonic() > deadline:
                truncated_reason = f"time budget ({int(_SEARCH_TIME_BUDGET_S)}s) exceeded"
                break
            if _is_probably_binary(fp):
                files_skipped_binary += 1
                continue
            try:
                with fp.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if matcher.search(line):
                            clean = line.rstrip("\r\n")
                            if len(clean) > _FIND_LINE_MAX_LEN:
                                clean = clean[:_FIND_LINE_MAX_LEN] + "…"
                            matches.append((fp, lineno))
                            files_with_matches.add(fp)
                            _emit_line(f"{fp}:{lineno}: {clean}")
                            if len(matches) >= _SEARCH_RESULTS_CAP:
                                truncated_reason = f"result cap ({_SEARCH_RESULTS_CAP})"
                                break
                        if time.monotonic() > deadline:
                            truncated_reason = (
                                f"time budget ({int(_SEARCH_TIME_BUDGET_S)}s) exceeded"
                            )
                            break
            except (PermissionError, OSError):
                continue
            if truncated_reason:
                break
    except Exception as exc:
        _emit_done(1)
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    if truncated_reason:
        _emit_line(f"[partial: {truncated_reason}]")
    _emit_done(0)

    if not matches:
        tail = f" in {glob_pat} files" if glob_pat else ""
        _tlog(f"✓ 0 matches for {pattern_raw!r}")
        return _ok(f"No matches for {pattern_raw!r}{tail}.")

    n         = len(matches)
    m         = len(files_with_matches)
    partial_t = f" (partial: {truncated_reason})" if truncated_reason else ""
    _tlog(f"✓ {n} match{'es' if n != 1 else ''} across {m} file{'s' if m != 1 else ''}")
    return _ok(
        f"{n} match{'es' if n != 1 else ''} for {pattern_raw!r} "
        f"across {m} file{'s' if m != 1 else ''}{partial_t}."
    )
