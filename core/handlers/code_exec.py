"""Handler: code_execution."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from core.handlers.shared import _ok, _err


def _handle_code_execution(action: str, params: dict) -> dict:
    code = params.get("code", params.get("script_path", ""))
    cwd  = params.get("working_directory", None)
    if not code:
        return _err("No code or command provided")

    if action == "run_python":
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        out = result.stdout or result.stderr
        return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])

    if action in ("run_shell", "git_command", "npm_command"):
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=60, cwd=cwd, shell=False,
            )
            out = (result.stdout or result.stderr or "").strip()
            return _ok(out[:2000]) if result.returncode == 0 else _err(out[:2000])
        except subprocess.TimeoutExpired:
            return _err("Command timed out after 60s")
        except Exception as exc:
            return _err(str(exc))

    if action == "run_script":
        p = Path(code).expanduser()
        if not p.exists():
            return _err(f"Script not found: {p}")
        result = subprocess.run(
            [sys.executable, str(p)] if p.suffix == ".py" else [str(p)],
            capture_output=True, text=True, timeout=60, cwd=cwd,
        )
        return _ok(result.stdout[:2000]) if result.returncode == 0 else _err(result.stderr[:2000])

    return _err(f"Unknown code action: {action}")
