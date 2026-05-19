"""Handler: file_operation — create, read, delete, rename, move, copy, list, search."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from core.handlers.shared import _ok, _err, request_confirmation
from core.handlers.paths import _resolve_file_operation_path, _find_folder
from core.signals import signals


# ── Phase 1 limits + budgets ──────────────────────────────────────────────────
_READ_FILE_MAX_BYTES    = 5 * 1024 * 1024   # 5 MB safety cap before reading
_READ_FILE_OUTPUT_CAP   = 50_000            # chars; truncate output past this
_LIST_DIR_CAP           = 500
_SEARCH_RESULTS_CAP     = 200
_SEARCH_TIME_BUDGET_S   = 30.0
_BATCH_DELETE_MAX       = 1000
_REPLACE_PREVIEW_CTX    = 50    # chars of context shown before/after first match
_FIND_LINE_MAX_LEN      = 200   # truncate very long matched lines in grep output

# Extension → friendly type label for file_info. Anything not listed shows just the suffix.
_EXT_TYPE_HINTS: dict[str, str] = {
    ".py": "Python source", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript React", ".jsx": "JavaScript React",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS",
    ".json": "JSON data", ".md": "Markdown", ".txt": "Text",
    ".log": "Log file", ".csv": "CSV data", ".tsv": "TSV data",
    ".xml": "XML", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
    ".ini": "Config", ".cfg": "Config", ".env": "Environment vars",
    ".pdf": "PDF", ".doc": "Word document", ".docx": "Word document",
    ".xls": "Excel sheet", ".xlsx": "Excel sheet",
    ".png": "PNG image", ".jpg": "JPEG image", ".jpeg": "JPEG image",
    ".gif": "GIF image", ".webp": "WebP image", ".svg": "SVG image",
    ".mp3": "MP3 audio", ".wav": "WAV audio", ".flac": "FLAC audio",
    ".mp4": "MP4 video", ".mov": "QuickTime video", ".mkv": "Matroska video",
    ".zip": "ZIP archive", ".tar": "TAR archive", ".gz": "Gzip archive",
    ".exe": "Windows executable", ".dll": "Windows library", ".bat": "Batch script",
    ".sh": "Shell script", ".ps1": "PowerShell script",
}

# Recursive walks (search_files, find_in_files) skip these noisy trees.
_SEARCH_PRUNE_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", "node_modules", ".venv", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".tox", ".idea", ".vscode",
})

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?\s*$", re.I)


def _format_human_size(n: int) -> str:
    """Format a byte count as a short human-readable string."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit, factor in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= factor:
            return f"{n / factor:.1f} {unit}"
    return f"{n} B"


def _parse_size_spec(spec) -> int | None:
    """Parse '1MB', '500KB', '2.5GB', '1024' into a byte count. None on bad input."""
    if spec is None:
        return None
    m = _SIZE_RE.match(str(spec))
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    factor = {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30}[unit]
    return int(n * factor)


def _is_probably_binary(path: Path) -> bool:
    """Sample first 4 KB; treat as binary if NULs present or >30% replacement chars
    after a utf-8 decode with errors='replace'. Used to gate replace_in_file, file_info
    line counts, and find_in_files content reads (Decision B in the Phase 3 plan)."""
    try:
        with path.open("rb") as fh:
            sample = fh.read(4096)
    except OSError:
        return True
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    try:
        decoded = sample.decode("utf-8", errors="replace")
    except Exception:
        return True
    if not decoded:
        return False
    replacements = decoded.count("�")
    return (replacements / len(decoded)) > 0.30


def _emit_to_terminal(text: str, success: bool = True, command: str | None = None) -> None:
    """Stream file-op output to the terminal panel, optionally prefixed with the command."""
    if command:
        signals.terminal_line_ready.emit(f"❯ {command}")
    for line in text.splitlines():
        signals.terminal_line_ready.emit(line)
    signals.terminal_done.emit(0 if success else 1)


def _strip_llm_path_placeholders(p: Path) -> Path:
    try:
        parts = list(p.parts)
    except (TypeError, ValueError, OSError):
        return p
    for i, part in enumerate(parts):
        if part.casefold() == ".keep":
            return Path(*parts[:i]) if i else p
    return p


def _locate_file(name: str) -> Path | None:
    """Find a file by exact name under common user roots. Bounded by
    _SEARCH_TIME_BUDGET_S and the prune list so a deep $HOME walk can't freeze
    the UI."""
    roots = [
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home(),
    ]
    deadline = time.monotonic() + _SEARCH_TIME_BUDGET_S
    for root in roots:
        if not root.exists():
            continue
        try:
            for dirpath, dirs, files in os.walk(str(root)):
                if time.monotonic() > deadline:
                    return None
                dirs[:] = [d for d in dirs if d.lower() not in _SEARCH_PRUNE_DIRS]
                if name in files:
                    candidate = Path(dirpath) / name
                    if candidate.is_file():
                        return candidate
        except (PermissionError, OSError):
            pass
    return None


def _raw_path_is_bare_filename(raw_path: str) -> bool:
    s = str(raw_path or "").strip().strip('"')
    if not s:
        return False
    try:
        p = Path(s.replace("\\", "/"))
    except (TypeError, ValueError):
        return False
    return len(p.parts) == 1


def _resolved_missing_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except (OSError, ValueError, RuntimeError):
        return str(path)


def _find_existing_item(path: Path) -> Path | None:
    """Locate a file OR directory by name. Bounded by _SEARCH_TIME_BUDGET_S and
    the prune list so a wildcard walk can't freeze the UI."""
    target = path.name
    if not target:
        return None

    deadline = time.monotonic() + _SEARCH_TIME_BUDGET_S

    def _walk_for(root: Path) -> Path | None:
        try:
            for dirpath, dirs, files in os.walk(str(root)):
                if time.monotonic() > deadline:
                    return None
                dirs[:] = [d for d in dirs if d.lower() not in _SEARCH_PRUNE_DIRS]
                if target in files:
                    return Path(dirpath) / target
                if target in dirs:
                    return Path(dirpath) / target
        except (PermissionError, OSError):
            return None
        return None

    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.exists() and ancestor.is_dir():
            hit = _walk_for(ancestor)
            if hit is not None:
                return hit
            break
        ancestor = ancestor.parent

    for root in (
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home(),
    ):
        if not root.exists():
            continue
        hit = _walk_for(root)
        if hit is not None:
            return hit
    return None


def _file_op_create_directory(params: dict) -> dict:
    raw_path = params.get("path", "")
    s = (raw_path or "").strip()
    if not s:
        return _err("No path provided")
    path = _strip_llm_path_placeholders(_resolve_file_operation_path(s))
    if path.exists() and path.is_file():
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
            return _ok(f"Created folder: {path.name}")
        except PermissionError:
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            return _err(str(exc))

    return request_confirmation(prompt, _do_mkdir)


def _handle_file_operation(action: str, params: dict, confirmed: bool = False) -> dict:
    raw_path = params.get("path", "")
    path     = _resolve_file_operation_path(raw_path) if raw_path else Path.home() / "jarvis_file.txt"

    if action == "create_directory":
        return _file_op_create_directory(params)

    if action == "create_file":
        path = _strip_llm_path_placeholders(path)
        content = params.get("content", "")
        content_stripped = (content or "").strip() if isinstance(content, str) else ""
        raw_n = (raw_path or "").replace("\\", "/")
        has_trailing = len(raw_n) > 0 and raw_n.rstrip().endswith("/")

        if not path.suffix and not has_trailing and not content_stripped:
            return _file_op_create_directory({"path": str(path), **{k: v for k, v in params.items() if k != "path"}})

        if not path.suffix:
            path = path / "jarvis_note.txt"

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

        def _do_create() -> dict:
            try:
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return _ok(f"Created: {path.name}")
            except PermissionError:
                return _err(f"Permission denied: {path}")
            except Exception as exc:
                return _err(str(exc))

        from core.personality import ask as _ask
        return request_confirmation(_ask("create_file", path_summary), _do_create)

    if action == "read_file":
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
            return _err(f"end_line ({end_line}) must be >= start_line ({start_line})")

        if not path.exists():
            found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                result = _err(f"File not found: {_resolved_missing_path(path)}")
                _emit_to_terminal(result["error"], success=False)
                return result

        try:
            size = path.stat().st_size
        except OSError as exc:
            result = _err(str(exc))
            _emit_to_terminal(result["error"], success=False)
            return result

        if size > _READ_FILE_MAX_BYTES:
            return _err(
                f"File too large to read: {_format_human_size(size)} "
                f"(cap: {_format_human_size(_READ_FILE_MAX_BYTES)}) — "
                f"use start_line/end_line to read a slice."
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            result = _err(f"Permission denied reading: {path.name}")
            _emit_to_terminal(result["error"], success=False)
            return result
        except Exception as exc:
            result = _err(str(exc))
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
        signals.terminal_line_ready.emit(f"❯ {cmd_label}")
        signals.terminal_line_ready.emit(f"── {path.name} ──")
        for line in body_out.splitlines():
            signals.terminal_line_ready.emit(line)
        signals.terminal_done.emit(0)
        return _ok(body_out)

    if action == "delete_file":
        if not path.exists():
            found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")
        try:
            full_path_str = str(path.resolve())
        except (OSError, ValueError):
            full_path_str = str(path)
        is_dir = path.is_dir()
        kind   = "Folder" if is_dir else "File"
        lines  = [f"{kind}: {full_path_str}"]
        if is_dir:
            try:
                n = sum(1 for _ in path.rglob("*"))
                lines.append(f"Contains: {n} item(s) — all will be permanently removed")
            except (PermissionError, OSError):
                lines.append("Note: all contents will be permanently removed")
        item_desc = "\n".join(lines)

        def _do_delete() -> dict:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return _ok(f"Deleted: {path.name}")
            except PermissionError:
                msg = f"Permission denied: {path.name}"
                return {"success": False, "output": msg, "error": msg}
            except Exception as exc:
                msg = str(exc)
                return {"success": False, "output": msg, "error": msg}

        from core.personality import ask as _ask
        if confirmed:
            return _do_delete()
        return request_confirmation(_ask("delete_file", item_desc), _do_delete)

    if action == "rename_file":
        if not path.exists():
            found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")
        new_name_raw = (params.get("new_name") or params.get("destination") or "").strip()
        if not new_name_raw:
            return _err("No new name provided for rename.")
        new_filename = Path(new_name_raw).name or new_name_raw
        dest_path    = path.parent / new_filename
        try:
            loc_str = str(path.parent.resolve())
        except (OSError, ValueError):
            loc_str = str(path.parent)
        rename_desc = f"From: {path.name}\nTo:   {new_filename}\nIn:   {loc_str}"

        def _do_rename() -> dict:
            try:
                if dest_path.exists():
                    msg = f"'{new_filename}' already exists in that location"
                    return {"success": False, "output": msg, "error": msg}
                path.rename(dest_path)
                return _ok(f"Renamed to {new_filename}")
            except PermissionError:
                msg = "Permission denied"
                return {"success": False, "output": msg, "error": msg}
            except Exception as exc:
                msg = str(exc)
                return {"success": False, "output": msg, "error": msg}

        from core.personality import ask as _ask
        return request_confirmation(_ask("rename_file", rename_desc), _do_rename)

    if action == "move_file":
        if not path.exists():
            found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(f"Cannot find {_resolved_missing_path(path)!r} — check the path and try again.")

        # Resolve destination once, here, so the flow is readable:
        # single-segment ("desktop") goes through the shortcut/fuzzy matcher;
        # anything else goes through the standard file-operation resolver.
        raw_dest_str = (params.get("destination") or "").strip()
        if not raw_dest_str:
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

        def _do_move() -> dict:
            try:
                shutil.move(str(captured_path), str(captured_dest))
                return _ok(f"Moved {captured_path.name} → {captured_final}")
            except Exception as exc:
                return _err(str(exc))

        return request_confirmation(move_desc, _do_move)

    if action == "copy_file":
        raw_dest_str = (params.get("destination") or "").strip()
        if not raw_dest_str:
            return _err("No destination provided")
        dest = _resolve_file_operation_path(raw_dest_str)
        try:
            shutil.copy2(str(path), str(dest))
            return _ok(f"Copied {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "list_directory":
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

    if action == "search_files":
        pattern         = params.get("pattern") or "*"
        modified_after  = params.get("modified_after")
        size_gt_raw     = params.get("size_gt")
        size_lt_raw     = params.get("size_lt")
        if not raw_path:
            base = Path.home()
        elif path.exists() and path.is_dir():
            base = path
        elif path.exists():
            return _err(f"Not a directory: {path}")
        else:
            found_dir = _find_folder(raw_path)
            if found_dir:
                base = found_dir
            else:
                return _err(f"Directory not found: {_resolved_missing_path(path)}")

        # Parse filters up-front so bad input fails fast with a helpful message.
        after_ts: float | None = None
        if modified_after:
            try:
                after_ts = datetime.strptime(str(modified_after).strip(), "%Y-%m-%d").timestamp()
            except (ValueError, TypeError):
                return _err("Invalid modified_after — use YYYY-MM-DD")

        size_gt = _parse_size_spec(size_gt_raw) if size_gt_raw is not None else None
        if size_gt_raw is not None and size_gt is None:
            return _err("Invalid size_gt — use e.g. '1MB', '500KB'")
        size_lt = _parse_size_spec(size_lt_raw) if size_lt_raw is not None else None
        if size_lt_raw is not None and size_lt is None:
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
            _emit_to_terminal(result["error"], success=False)
            return result

        cmd_label = f"find '{pattern}' in {base.name}/"
        if not matches:
            _emit_to_terminal("No matching files found.", command=cmd_label)
            return _ok("No matching files found.")

        lines  = [f"[FILE] {p}" for p in matches]
        header = f"── {len(lines)} result(s) for '{pattern}' in {base.name}/ ──"
        body_lines = [header, *lines]
        if truncated_reason:
            body_lines.append(f"[partial: {truncated_reason}]")

        _emit_to_terminal("\n".join(body_lines), command=cmd_label)
        return _ok("\n".join(p.name for p in matches))

    if action == "append_file":
        content = params.get("content", "")
        if not isinstance(content, str) or content == "":
            return _err("Missing 'content' to append")
        use_timestamp = bool(params.get("timestamp", False))

        if not path.exists():
            found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(
                    f"File not found: {_resolved_missing_path(path)} — use create_file to make a new one"
                )
        if path.is_dir():
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
            return _err(f"Permission denied writing: {path.name}")
        except Exception as exc:
            return _err(str(exc))

        try:
            full_path_str = str(path.resolve())
        except (OSError, ValueError, RuntimeError):
            full_path_str = str(path)
        _emit_to_terminal(
            f"Appended {written} chars to {full_path_str}",
            command=f"append → {path.name}",
        )
        return _ok(f"Appended {written} chars to {path.name}")

    if action == "file_info":
        if not path.exists():
            found = _find_existing_item(path) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(f"Not found: {_resolved_missing_path(path)}")

        try:
            st = path.stat()
        except OSError as exc:
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
        return _ok(body)

    if action == "replace_in_file":
        find_text    = params.get("find", "")
        replace_text = params.get("replace", "")
        try:
            count_arg = int(params.get("count", -1))
        except (TypeError, ValueError):
            count_arg = -1

        if not isinstance(find_text, str) or find_text == "":
            return _err("Missing 'find' text to search for")
        if not isinstance(replace_text, str):
            return _err("Missing 'replace' text")

        if not path.exists():
            found = _locate_file(path.name) if _raw_path_is_bare_filename(raw_path) else None
            if found:
                path = found
            else:
                return _err(f"File not found: {_resolved_missing_path(path)}")

        if _is_probably_binary(path):
            return _err(
                f"{path.name} looks like a binary file — replace_in_file only supports text files."
            )

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return _err(f"{path.name} is not valid UTF-8 text — refusing to edit.")
        except PermissionError:
            return _err(f"Permission denied reading: {path.name}")
        except Exception as exc:
            return _err(str(exc))

        occurrences = content.count(find_text)
        if occurrences == 0:
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
                return _ok(msg)
            except PermissionError:
                return _err(f"Permission denied writing: {captured_path.name}")
            except Exception as exc:
                return _err(str(exc))

        return request_confirmation(prompt, _do_replace)

    if action == "batch_delete":
        glob_pat  = (params.get("pattern") or "").strip()
        recursive = bool(params.get("recursive", False))

        if not glob_pat:
            return _err("Missing 'pattern' (glob, e.g. '*.tmp')")

        if not path.exists():
            found_dir = _find_folder(raw_path) if raw_path else None
            if found_dir:
                path = found_dir
            else:
                return _err(f"Directory not found: {raw_path or path}")
        if not path.is_dir():
            return _err(f"Not a directory: {path}")

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
            return _err(f"Permission denied scanning: {path}")
        except Exception as exc:
            return _err(str(exc))

        if not candidates:
            return _ok(f"No files matched {glob_pat!r} in {path.name}/")

        if len(candidates) > _BATCH_DELETE_MAX:
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
            signals.terminal_line_ready.emit(f"❯ {captured_label}")
            for fp in captured_files:
                try:
                    sz = fp.stat().st_size
                except OSError:
                    sz = 0
                try:
                    fp.unlink()
                    deleted += 1
                    freed_bytes += sz
                    signals.terminal_line_ready.emit(f"Deleted: {fp}")
                except Exception as exc:
                    errors.append(f"{fp.name}: {exc}")
                    signals.terminal_line_ready.emit(f"Failed:  {fp} — {exc}")
            signals.terminal_done.emit(0 if not errors else 1)

            base_msg = f"Deleted {deleted} file(s), freed {_format_human_size(freed_bytes)}"
            if errors:
                err_tail = "; ".join(errors[:3])
                if len(errors) > 3:
                    err_tail += f"; +{len(errors) - 3} more"
                return {
                    "success": deleted > 0,
                    "output":  f"{base_msg}. {len(errors)} failed: {err_tail}",
                    "error":   f"{len(errors)} file(s) could not be deleted",
                }
            return _ok(base_msg)

        return request_confirmation(prompt, _do_batch_delete)

    if action == "find_in_files":
        pattern_raw = params.get("pattern", "")
        if not isinstance(pattern_raw, str) or pattern_raw == "":
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
                return _err(f"Path not found: {raw_path}")

        flags = 0 if case_sensitive else re.IGNORECASE
        if use_regex:
            try:
                matcher = re.compile(pattern_raw, flags)
            except re.error as exc:
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
        signals.terminal_line_ready.emit(f"❯ {cmd_label}")

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
                                signals.terminal_line_ready.emit(f"{fp}:{lineno}: {clean}")
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
            signals.terminal_done.emit(1)
            return _err(str(exc))

        if truncated_reason:
            signals.terminal_line_ready.emit(f"[partial: {truncated_reason}]")
        signals.terminal_done.emit(0)

        if not matches:
            tail = f" in {glob_pat} files" if glob_pat else ""
            return _ok(f"No matches for {pattern_raw!r}{tail}.")

        n         = len(matches)
        m         = len(files_with_matches)
        partial_t = f" (partial: {truncated_reason})" if truncated_reason else ""
        return _ok(
            f"{n} match{'es' if n != 1 else ''} for {pattern_raw!r} "
            f"across {m} file{'s' if m != 1 else ''}{partial_t}."
        )

    return _err(f"Unknown file action: {action}")
