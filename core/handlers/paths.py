"""Path resolution helpers for file operations and screenshots."""

from __future__ import annotations

import difflib
import os
from datetime import datetime
from pathlib import Path


_USER_FOLDERS = frozenset({
    "documents", "downloads", "desktop", "pictures", "music",
    "videos", "onedrive", "appdata",
})

_HOME_WALK_MAX_DEPTH = 8
_HOME_PRUNE_DIR_NAMES: frozenset[str] = frozenset(
    n.lower() for n in (
        "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv",
        "npm-cache", ".yarn", ".nuget", "packages",
    )
)
_HOME_PRUNE_PATH_FRAGMENTS: tuple[str, ...] = (
    "\\appdata\\local\\packages\\",
    "\\appdata\\local\\pip\\",
    "\\node_modules\\",
)


def _default_create_parent() -> Path:
    h = Path.home()
    key = (os.getenv("JARVIS_DEFAULT_CREATE_PARENT") or "Documents").strip()
    m = {
        "documents": h / "Documents",
        "desktop": h / "Desktop",
        "downloads": h / "Downloads",
        "home": h,
    }
    p = m.get(key.lower(), h / "Documents")
    try:
        return p if p.exists() or key.lower() == "home" else (h / "Documents")
    except OSError:
        return h / "Documents"


def _prune_home_walk_dirnames(pdir: Path, dirnames: list[str], home: Path) -> None:
    low = str(pdir).lower() + "\\"
    if any(frag in low for frag in _HOME_PRUNE_PATH_FRAGMENTS):
        dirnames.clear()
        return
    to_remove = {d for d in dirnames if d.lower() in _HOME_PRUNE_DIR_NAMES or d.startswith(".")}
    if not to_remove:
        return
    dirnames[:] = [d for d in dirnames if d not in to_remove]


def _find_all_exact_name_in_profile(home: Path, n_lower: str) -> list[Path]:
    home = home.resolve()
    if not n_lower or not home.exists():
        return []
    out: list[Path] = []
    try:
        for dirpath, dirnames, _ in os.walk(str(home), topdown=True):
            pdir = Path(dirpath)
            try:
                depth = len(pdir.relative_to(home).parts)
            except ValueError:
                depth = 0
            if depth > _HOME_WALK_MAX_DEPTH:
                dirnames.clear()
                continue
            _prune_home_walk_dirnames(pdir, dirnames, home)
            for dn in list(dirnames):
                if dn.lower() == n_lower:
                    c = pdir / dn
                    if c.is_dir():
                        out.append(c)
    except (PermissionError, OSError, ValueError):
        pass
    return out


def _pick_best_of_matches(cands: list[Path], home: Path) -> Path:
    def _key(p: Path) -> tuple:
        p = p.resolve()
        try:
            d = len(p.relative_to(home).parts)
        except ValueError:
            d = 99
        doc = 0 if "Documents" in p.parts else 1
        return (d, doc, str(p).lower())

    return sorted(cands, key=_key)[0]


def _expand_path_string(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return t
    t = os.path.expandvars(t)
    return str(Path(t).expanduser())


def _safe_path(path_str: str) -> Path:
    if not path_str:
        return Path.home() / "jarvis_file.txt"

    p = Path(_expand_path_string(path_str))
    home = Path.home()
    parts = p.parts

    if (len(parts) >= 3
            and parts[0].upper().rstrip("\\") in ("C:", "C:\\")
            and parts[1].lower() == "users"
            and parts[2].lower() != home.name.lower()
            and not (Path(parts[0]) / parts[1] / parts[2]).exists()):
        rest = parts[3:]
        if parts[2].lower() in _USER_FOLDERS:
            p = home / parts[2] / Path(*rest) if rest else home / parts[2]
        else:
            p = home / Path(*rest) if rest else home

    elif not p.is_absolute() and parts and parts[0].lower() in _USER_FOLDERS:
        p = home / Path(*parts)

    return p


def _find_folder(name: str) -> Path | None:
    home = Path.home()
    n = name.strip().lower()
    if not n:
        return None

    shortcuts: dict[str, Path] = {
        "downloads": home / "Downloads",
        "download":  home / "Downloads",
        "desktop":   home / "Desktop",
        "documents": home / "Documents",
        "document":  home / "Documents",
        "docs":      home / "Documents",
        "pictures":  home / "Pictures",
        "pics":      home / "Pictures",
        "photos":    home / "Pictures",
        "music":     home / "Music",
        "videos":    home / "Videos",
        "movies":    home / "Videos",
    }
    if n in shortcuts:
        p = shortcuts[n]
        return p if p.exists() else None

    for root in (
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home,
        home / "OneDrive" / "Documents",
        home / "OneDrive",
    ):
        if not root.exists():
            continue
        try:
            for p in root.iterdir():
                if p.is_dir() and p.name.lower() == n:
                    return p
        except (PermissionError, OSError):
            pass

    cands = _find_all_exact_name_in_profile(home, n)
    if cands:
        uniq: dict[str, Path] = {}
        for c in cands:
            k = str(c.resolve())
            if k not in uniq:
                uniq[k] = c
        u = list(uniq.values())
        if len(u) == 1:
            return u[0]
        return _pick_best_of_matches(u, home)

    candidates: list[tuple[float, Path]] = []
    for root in (home / "Documents", home / "Desktop", home / "Downloads"):
        root = root.resolve()
        if not root.exists():
            continue
        try:
            for dirpath, dirnames, _ in os.walk(str(root), topdown=True):
                pdir = Path(dirpath)
                try:
                    if len(pdir.relative_to(root).parts) > 5:
                        dirnames.clear()
                        continue
                except ValueError:
                    pass
                for dn in list(dirnames):
                    p = pdir / dn
                    if not p.is_dir():
                        continue
                    score = difflib.SequenceMatcher(None, p.name.lower(), n).ratio()
                    if score > 0.82:
                        candidates.append((score, p))
        except (PermissionError, OSError):
            pass

    if candidates:
        def _key(item: tuple[float, Path]) -> tuple:
            sc, pth = item
            under_docs = 1 if "Documents" in pth.parts else 0
            return (sc, under_docs, -len(pth.parts))

        candidates.sort(key=_key, reverse=True)
        return candidates[0][1]
    return None


def _resolve_file_operation_path(raw: str) -> Path:
    if not raw or not str(raw).strip():
        return Path.home() / "jarvis_file.txt"
    s = _expand_path_string(str(raw).strip())
    p = Path(s.replace("\\", "/"))
    if p.is_absolute():
        return _safe_path(s)
    if not p.parts:
        return Path.home() / "jarvis_file.txt"
    first, *rest = p.parts
    if first in (".", ".."):
        return _safe_path(s)
    found = _find_folder(first)
    if found is not None:
        if not rest:
            return found
        return found / Path(*rest)
    return _default_create_parent() / Path(*p.parts)


def _resolve_screenshot_path(save_param: str | None) -> tuple[str, str | None]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"JARVIS_{ts}.png"

    if not save_param:
        return str(Path.home() / "Desktop" / fname), None

    p = Path(_expand_path_string(str(save_param)))

    if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return str(p), None

    if p.is_dir():
        return str(p / fname), None

    if len(p.parts) == 1:
        found = _find_folder(save_param)
        if found:
            return str(found / fname), None
        return "", save_param

    if p.is_absolute():
        try:
            p.mkdir(parents=True, exist_ok=True)
            return str(p / fname), None
        except Exception:
            pass

    return str(Path.home() / "Desktop" / fname), None
