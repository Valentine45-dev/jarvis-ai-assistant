"""Shared constants, helpers, and terminal-signal emission for the file_ops
package (R2-17b split).

Everything here is engine-/action-agnostic plumbing used by the per-action
modules (create, read_write, replace, move_rename, delete, batch, search, info)
and the dispatch in ``__init__``. The package's path *resolution* still lives in
``core.handlers.paths`` — this module only holds the file_ops-local bits.

ALL terminal-signal access funnels through this module (``signals`` +
``_emit_to_terminal`` / ``_emit_line`` / ``_emit_done``) so a test can neutralise
emission with a single ``patch.object(file_ops._common, "signals", ...)``.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

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


# ── Terminal emission (single funnel — patch _common.signals in tests) ────────
def _emit_to_terminal(text: str, success: bool = True, command: str | None = None) -> None:
    """Stream file-op output to the terminal panel, optionally prefixed with the command."""
    if command:
        signals.terminal_line_ready.emit(f"❯ {command}")
    for line in text.splitlines():
        signals.terminal_line_ready.emit(line)
    signals.terminal_done.emit(0 if success else 1)


def _emit_line(text: str) -> None:
    """Emit one streamed terminal line (used by read_file / batch_delete / find_in_files)."""
    signals.terminal_line_ready.emit(text)


def _emit_done(code: int = 0) -> None:
    """Signal the end of a streamed terminal block (0 = ok, non-zero = error)."""
    signals.terminal_done.emit(code)


# ── Size formatting / parsing ─────────────────────────────────────────────────
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


# ── Path helpers (file_ops-local; resolution lives in core.handlers.paths) ────
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
