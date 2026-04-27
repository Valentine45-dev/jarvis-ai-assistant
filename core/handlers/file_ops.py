"""Handler: file_operation — create, read, delete, rename, move, copy, list, search."""

from __future__ import annotations

import shutil
from pathlib import Path

from core.handlers.shared import _ok, _err, request_confirmation
from core.handlers.paths import _resolve_file_operation_path, _find_folder


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
    roots = [
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home(),
    ]
    for root in roots:
        try:
            for p in root.rglob(name):
                if p.is_file():
                    return p
        except (PermissionError, OSError):
            pass
    return None


def _find_existing_item(path: Path) -> Path | None:
    target = path.name
    if not target:
        return None

    ancestor = path.parent
    while ancestor != ancestor.parent:
        if ancestor.exists() and ancestor.is_dir():
            try:
                for found in ancestor.rglob(target):
                    if found.exists():
                        return found
            except (PermissionError, OSError):
                pass
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
        try:
            for found in root.rglob(target):
                if found.exists():
                    return found
        except (PermissionError, OSError):
            pass
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
        f"Create this folder, sir? (Parent folders are created if needed.)\n\n"
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
    dest     = _resolve_file_operation_path(params["destination"]) if params.get("destination") else None

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
        if not path.exists():
            found = _locate_file(path.name)
            if found:
                path = found
            else:
                return _err(f"File not found: {path.name}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return _ok(content[:2000])
        except PermissionError:
            return _err(f"Permission denied reading: {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "delete_file":
        if not path.exists():
            found = _find_existing_item(path)
            if found:
                path = found
            else:
                return _err(f"Cannot find {path.name!r} — check the name and try again.")
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
            found = _find_existing_item(path)
            if found:
                path = found
            else:
                return _err(f"Cannot find {path.name!r} — check the name and try again.")
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
            found = _find_existing_item(path)
            if found:
                path = found
        raw_dest_str = (params.get("destination") or "").strip()
        if (
            raw_dest_str
            and "/" not in raw_dest_str
            and "\\" not in raw_dest_str
            and _find_folder(raw_dest_str) is None
        ):
            dest = path.parent / raw_dest_str
        if dest is None:
            return _err("No destination provided")
        try:
            shutil.move(str(path), str(dest))
            return _ok(f"Moved {path.name} → {dest.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "copy_file":
        if dest is None:
            return _err("No destination provided")
        try:
            shutil.copy2(str(path), str(dest))
            return _ok(f"Copied {path.name}")
        except Exception as exc:
            return _err(str(exc))

    if action == "list_directory":
        if not path.exists():
            found_dir = _find_folder(raw_path) if raw_path else None
            if found_dir:
                path = found_dir
            else:
                return _err(f"Directory not found: {raw_path or path}")
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            lines   = []
            for p in entries[:50]:
                icon = "📁" if p.is_dir() else "📄"
                lines.append(f"{icon} {p.name}")
            summary = f"{path.name}/ — {len(lines)} items:\n" + "\n".join(lines)
            return _ok(summary)
        except PermissionError:
            return _err(f"Permission denied: {path}")
        except Exception as exc:
            return _err(str(exc))

    if action == "search_files":
        pattern = params.get("pattern", "*")
        base    = path if path.is_dir() else Path.home()
        try:
            results = [str(p) for p in base.rglob(pattern)][:30]
            if not results:
                return _ok("No matching files found.")
            return _ok("\n".join(Path(r).name for r in results))
        except Exception as exc:
            return _err(str(exc))

    return _err(f"Unknown file action: {action}")
