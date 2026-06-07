"""Handler: file_operation — package entry point + action dispatch (R2-17b).

The 1220-LOC monolith is decomposed into this package: shared plumbing in
``_common``, per-action logic in category modules (create / read_write /
replace / move_rename / delete / batch / search / info). This module keeps the
sole public symbol ``_handle_file_operation`` (imported by ``core.executor``)
and routes each action to its ``_op_*`` via ``_DISPATCH``. Path resolution lives
in ``core.handlers.paths``.
"""

from __future__ import annotations

from pathlib import Path

# _ok re-exported (unused here) so the package root keeps advertising the shared
# response helpers — test_audit_promoted asserts _ok/_err stay singletons.
from core.handlers.shared import _ok, _err
from core.handlers.paths import _resolve_file_operation_path
from core.handlers.file_ops.create import _op_create_directory, _op_create_file
from core.handlers.file_ops.read_write import _op_read_file, _op_append_file
from core.handlers.file_ops.replace import _op_replace_in_file
from core.handlers.file_ops.move_rename import (
    _op_rename_file, _op_move_file, _op_copy_file,
)
from core.handlers.file_ops.delete import _op_delete_file
from core.handlers.file_ops.batch import _op_batch_delete
from core.handlers.file_ops.search import (
    _op_list_directory, _op_search_files, _op_find_in_files,
)
from core.handlers.file_ops.info import _op_file_info

# action name → handler. Every handler takes (params, *, path, raw_path, confirmed).
_DISPATCH = {
    "create_directory": _op_create_directory,
    "create_file":      _op_create_file,
    "read_file":        _op_read_file,
    "append_file":      _op_append_file,
    "replace_in_file":  _op_replace_in_file,
    "rename_file":      _op_rename_file,
    "move_file":        _op_move_file,
    "copy_file":        _op_copy_file,
    "delete_file":      _op_delete_file,
    "batch_delete":     _op_batch_delete,
    "list_directory":   _op_list_directory,
    "search_files":     _op_search_files,
    "find_in_files":    _op_find_in_files,
    "file_info":        _op_file_info,
}


def _handle_file_operation(action: str, params: dict, confirmed: bool = False) -> dict:
    raw_path = params.get("path", "")
    path = _resolve_file_operation_path(raw_path) if raw_path else Path.home() / "jarvis_file.txt"
    op = _DISPATCH.get(action)
    if op is None:
        return _err(f"Unknown file action: {action}")
    return op(params, path=path, raw_path=raw_path, confirmed=confirmed)
