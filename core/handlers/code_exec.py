"""Handler: code_execution."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from core.handlers.shared import _ok, _err

# Background processes launched via run_background — pid → Popen
_bg_procs: dict[int, "subprocess.Popen[str]"] = {}


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n[truncated — {len(text)} chars total]"
    return text


def _handle_code_execution(action: str, params: dict) -> dict:
    code = params.get("code", params.get("script_path", ""))
    cwd  = params.get("working_directory", None)

    # ── PowerShell ────────────────────────────────────────────────────────────
    if action == "run_powershell":
        if not code:
            return _err("No PowerShell command provided")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            return _ok(out) if result.returncode == 0 else _err(out)
        except subprocess.TimeoutExpired:
            return _err("PowerShell command timed out after 60s")
        except FileNotFoundError:
            return _err("powershell.exe not found on this system")
        except Exception as exc:
            return _err(str(exc))

    # ── Command Prompt ────────────────────────────────────────────────────────
    if action == "run_cmd":
        if not code:
            return _err("No CMD command provided")
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", code],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            return _ok(out) if result.returncode == 0 else _err(out)
        except subprocess.TimeoutExpired:
            return _err("CMD command timed out after 60s")
        except FileNotFoundError:
            return _err("cmd.exe not found on this system")
        except Exception as exc:
            return _err(str(exc))

    # ── Package install ───────────────────────────────────────────────────────
    if action == "install_package":
        package = params.get("package") or code
        if not package:
            return _err("No package name provided")
        manager = (params.get("manager") or "pip").lower()
        if manager == "pip":
            pip_bin = Path(sys.executable).parent / ("pip.exe" if sys.platform == "win32" else "pip")
            if not pip_bin.exists():
                # venv created without pip — bootstrap it silently then retry
                subprocess.run(
                    [sys.executable, "-m", "ensurepip", "--upgrade"],
                    capture_output=True, timeout=30,
                )
            if pip_bin.exists():
                cmd = [str(pip_bin), "install", package]
            else:
                cmd = [sys.executable, "-m", "pip", "install", package]
        elif manager in ("npm", "node"):
            cmd = ["npm", "install", package]
        elif manager == "uv":
            cmd = ["uv", "add", package]
        else:
            return _err(f"Unknown package manager {manager!r}. Use pip, npm, or uv.")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            return _ok(out) if result.returncode == 0 else _err(out)
        except subprocess.TimeoutExpired:
            return _err("Package install timed out after 120s")
        except Exception as exc:
            return _err(str(exc))

    # ── Background execution ──────────────────────────────────────────────────
    if action == "run_background":
        if not code:
            return _err("No command provided")
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            proc = subprocess.Popen(
                args, cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _bg_procs[proc.pid] = proc
            return _ok(f"Started in background — PID {proc.pid}")
        except Exception as exc:
            return _err(str(exc))

    # ── Kill process ──────────────────────────────────────────────────────────
    if action == "kill_process":
        pid  = params.get("pid")
        name = params.get("process_name") or params.get("app_name") or ""
        try:
            import psutil
        except ImportError:
            return _err("psutil not installed — run: pip install psutil")

        if pid:
            try:
                p = psutil.Process(int(pid))
                pname = p.name()
                p.kill()
                _bg_procs.pop(int(pid), None)
                return _ok(f"Killed {pname} (PID {pid})")
            except psutil.NoSuchProcess:
                return _err(f"No process with PID {pid}")
            except Exception as exc:
                return _err(str(exc))

        if name:
            killed = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if name.lower() in (proc.info["name"] or "").lower():
                        proc.kill()
                        killed.append(f"{proc.info['name']} (PID {proc.info['pid']})")
                        _bg_procs.pop(proc.info["pid"], None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if killed:
                return _ok(f"Killed: {', '.join(killed)}")
            return _err(f"No process matching {name!r}")

        return _err("Provide pid or process_name to kill a process")

    # ── Standard actions ──────────────────────────────────────────────────────
    if not code:
        return _err("No code or command provided")

    if action == "run_python":
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30, cwd=cwd,
        )
        out = _truncate((result.stdout or result.stderr or "").strip())
        return _ok(out) if result.returncode == 0 else _err(out)

    if action in ("run_shell", "git_command", "npm_command"):
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            result = subprocess.run(
                args, capture_output=True, text=True,
                timeout=60, cwd=cwd, shell=False,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            return _ok(out) if result.returncode == 0 else _err(out)
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
        out = _truncate((result.stdout or result.stderr or "").strip())
        return _ok(out) if result.returncode == 0 else _err(out)

    return _err(f"Unknown code action: {action}")
