"""Handler: automation_task — workflow CRUD and run_workflow step execution."""

from __future__ import annotations

from pathlib import Path
import threading

from core.handlers.shared import (
    _ok,
    _err,
    _tlog,
    _tlog_step,
    _enter_workflow_step,
    _leave_workflow_step,
)

_DANGEROUS_STEPS: frozenset[tuple[str, str]] = frozenset({
    # delete_file is NOT here — requires_confirmation:true on the workflow
    # already gets the user's explicit go-ahead before execution starts.
    # Keeping it here caused a double-block: user confirms, executor refuses anyway.
    ("system_control",  "shutdown"),
    ("system_control",  "restart"),
    ("system_control",  "sleep"),
    ("close_app",       "force_quit"),
    ("code_execution",  "kill_process"),  # destructive — must run standalone
})

_CONFIRMATION_REQUIRED_ACTIONS: frozenset[tuple[str, str]] = frozenset({
    ("automation_task", "remove_workflow"),
    ("system_control",  "shutdown"),
    ("system_control",  "restart"),
    ("system_control",  "sleep"),
    ("close_app",       "force_quit"),
})

_KNOWN_STEP_INTENTS: frozenset[str] = frozenset({
    "open_app", "close_app", "search_web", "type_text", "control_mouse",
    "system_control", "file_operation", "browser_automation",
    "read_screen", "reminder_task", "jarvis_meta", "code_execution",
    "document_creation",
})


def _yield_ui() -> None:
    """Keep Qt responsive while long workflow steps execute on the main thread."""
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass


# R3-1/R3-2: workflow steps run on the Qt main thread and pump processEvents()
# between steps, which can re-enter dispatch (a typed command, a cron fire, a mic
# result). This counter marks "a workflow is actively executing" so main.py can
# reject re-entrant commands and drop scheduled fires while busy. A COUNTER (not a
# bool) because a confirmation pause resumes via _resume_after_confirm, which calls
# _run_from again — nested spans must not clear the flag early. Mirrors the
# module-level is_document_generation_in_flight() pattern (R2-15).
_workflow_depth = 0


def is_workflow_in_flight() -> bool:
    """True while any _run_from / _resume_after_confirm frame is executing."""
    return _workflow_depth > 0


def _handle_automation_task(action: str, params: dict) -> dict:
    from core.automation import workflow_library

    if action == "list_workflows":
        workflows = workflow_library.list_all()
        if not workflows:
            return _ok("No workflows defined.")
        lines = [
            f"- {w['name']}  [{w['id']}]  {'ON' if w.get('enabled') else 'OFF'}"
            for w in workflows
        ]
        return _ok("\n".join(lines))

    if action == "create_workflow":
        task_name = params.get("task_name", "")
        steps     = params.get("steps", [])
        trigger   = (params.get("trigger") or "Manual").strip() or "Manual"
        _tlog(f"❯ create workflow {task_name!r}")
        if not task_name:
            _tlog("✗ no task_name provided")
            return _err("No task_name provided for workflow creation.")
        if not isinstance(steps, list) or not steps:
            _tlog("✗ steps must be a non-empty list")
            return _err("Steps must be a non-empty list.")
        slug = task_name.lower().replace(" ", "_")
        if workflow_library.get(slug) is not None:
            _tlog(f"✗ workflow {task_name!r} already exists")
            return _err(f"Workflow '{task_name}' already exists.")
        for i, step in enumerate(steps, 1):
            if isinstance(step, str):
                continue  # validated at runtime when ask_claude parses it
            if not isinstance(step, dict):
                _tlog(f"✗ step {i} must be a dict or string")
                return _err(f"Step {i} must be a dict or string.")
            s_intent = step.get("intent", "")
            s_action = step.get("action", "")
            if not s_intent:
                _tlog(f"✗ step {i} is missing 'intent'")
                return _err(f"Step {i} is missing 'intent'.")
            if s_intent not in _KNOWN_STEP_INTENTS:
                _tlog(f"✗ step {i} has unrecognised intent {s_intent!r}")
                return _err(f"Step {i} has unrecognised intent '{s_intent}'.")
            if (s_intent, s_action) in _DANGEROUS_STEPS:
                _tlog(f"✗ step {i} contains dangerous action {s_action!r}")
                return _err(f"Step {i} contains dangerous action '{s_action}'.")
        wf = {
            "id": slug, "name": task_name, "trigger": trigger,
            "enabled": True, "last_run": "", "steps": steps,
        }
        # F-3: optional cron expression for auto-fire. Validated lightly here
        # (just non-empty); the scheduler itself silently skips invalid
        # expressions at fire-time rather than blocking workflow creation.
        schedule = (params.get("schedule") or "").strip()
        if schedule:
            wf["schedule"] = schedule
        workflow_library.add(wf)
        sched_note = f" — scheduled '{schedule}'" if schedule else ""
        _tlog(f"✓ saved — {len(steps)} step{'s' if len(steps) != 1 else ''}{sched_note}")
        return _ok(f"Workflow '{task_name}' created with {len(steps)} step(s){sched_note}.")

    if action == "remove_workflow":
        task_name = params.get("task_name", "")
        if not task_name:
            return _err("No task_name provided.")
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow '{task_name}' not found.")
        workflow_library.remove(wf["id"])
        return _ok(f"Workflow '{wf['name']}' deleted.")

    if action == "remove_all_workflows":
        from core.handlers.shared import request_confirmation
        _tlog("❯ remove all workflows")
        workflows = workflow_library.list_all()
        n = len(workflows)
        if n == 0:
            _tlog("✗ no workflows to delete")
            return _err("No workflows to delete")

        def _do_remove_all() -> dict:
            deleted = 0
            errors: list[str] = []
            for wf in workflow_library.list_all():
                try:
                    if workflow_library.remove(wf["id"]):
                        deleted += 1
                    else:
                        errors.append(wf.get("name") or wf.get("id") or "?")
                except Exception as exc:
                    errors.append(f"{wf.get('name') or wf.get('id') or '?'}: {exc}")
            if errors:
                tail = "; ".join(errors[:3])
                if len(errors) > 3:
                    tail += f"; +{len(errors) - 3} more"
                _tlog(f"✗ {len(errors)} workflow(s) could not be deleted (deleted {deleted})")
                return {
                    "success": deleted > 0,
                    "output":  f"Deleted {deleted} workflow(s). {len(errors)} failed: {tail}",
                    "error":   f"{len(errors)} workflow(s) could not be deleted",
                }
            _tlog(f"✓ deleted {deleted} workflow{'s' if deleted != 1 else ''}")
            return _ok(f"Deleted {deleted} workflow{'s' if deleted != 1 else ''}.")

        prompt = (
            f"Delete all {n} saved workflow{'s' if n != 1 else ''}? "
            f"This cannot be undone."
        )
        _tlog(f"⚠ awaiting confirmation — {n} workflow{'s' if n != 1 else ''}")
        return request_confirmation(prompt, _do_remove_all)

    if action == "rename_workflow":
        task_name = params.get("task_name", "")
        new_name  = params.get("new_name", "")
        if not task_name or not new_name:
            return _err("Both task_name and new_name are required.")
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow '{task_name}' not found.")
        new_slug = new_name.lower().replace(" ", "_")
        if new_slug != wf["id"] and workflow_library.get(new_slug) is not None:
            return _err(f"A workflow named '{new_name}' already exists.")
        workflow_library.rename(wf["id"], new_name)
        return _ok(f"Workflow renamed to '{new_name}'.")

    # run_workflow
    import time as _time

    from core.executor import dispatch  # late import — executor is fully loaded by runtime
    from core.handlers.shared import get_pending_confirmation, request_confirmation
    from core.workflow_metrics import workflow_metrics

    steps     = params.get("steps", [])
    task_name = params.get("task_name", "")
    workflow_id: str = ""

    _tlog(f"❯ workflow: {task_name or '(inline)'}")

    # If task_name resolves to a saved workflow, always prefer its persisted
    # step list over any inline steps from model output.
    if task_name:
        wf = workflow_library.get(task_name)
        if wf is not None:
            if not wf.get("enabled", True):
                _tlog(f"✗ workflow {wf['name']!r} is disabled")
                return _err(f"Workflow '{wf['name']}' is disabled.")
            steps       = wf.get("steps", [])
            workflow_id = wf.get("id", "")
        elif not steps:
            _tlog(f"✗ workflow not found: {task_name!r}")
            return _err(f"Workflow not found: {task_name!r}")

    if not steps:
        _tlog("✗ no steps provided")
        return _err("No steps provided in automation task")

    for step in steps:
        if isinstance(step, str):
            continue  # string steps are parsed at runtime
        intent   = step.get("intent", "")
        s_action = step.get("action", "")
        if (intent, s_action) in _DANGEROUS_STEPS:
            _tlog(f"✗ workflow contains dangerous step {s_action!r}")
            return _err(f"Workflow contains dangerous step '{s_action}' — run manually.")

    total = len(steps)
    state: dict = {
        "results": [],
        "all_ok": True,
        "last_step_intent": "",
        "last_step_action": "",
        "quit_application": False,
        "last_python_file": "",
        "last_directory": "",
    }

    def _append_step_result(idx: int, sub: dict) -> None:
        state["results"].append(
            f"Step {idx}: {'OK' if sub.get('success') else 'FAIL'} — {sub.get('output') or sub.get('error')}"
        )

    def _absorb_step_into_state(step: dict, sub: dict) -> None:
        """Mirror the post-step state updates: last_step_*, last_python_file,
        last_directory, quit_application. Called after both confirm-resume and
        direct-success paths."""
        state["last_step_intent"] = (step.get("intent") or "").strip()
        state["last_step_action"] = (step.get("action") or "").strip()
        if sub.get("quit_application"):
            state["quit_application"] = True
        if (
            state["last_step_intent"] == "file_operation"
            and state["last_step_action"] == "create_file"
        ):
            params = step.get("parameters") or {}
            path = str(params.get("path") or "").strip()
            if path.lower().endswith(".py"):
                state["last_python_file"] = path
                state["last_directory"] = str(Path(path).parent)

    def _ask_claude_step(step_text: str, step_n: int) -> dict:
        holder: dict[str, dict] = {}

        def _run() -> None:
            from core.brain import ask_claude
            holder["result"] = ask_claude(
                step_text,
                use_memory=False,
                context={
                    "workflow_step_index": step_n,
                    "workflow_total_steps": total,
                    "workflow_last_python_file": state["last_python_file"],
                    "workflow_last_directory": state["last_directory"],
                    "workflow_last_output": state["results"][-1] if state["results"] else "",
                },
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        while t.is_alive():
            _yield_ui()
            t.join(0.03)
        return holder.get("result", {"intent": "unknown"})

    def _between_step_blank() -> None:
        """UX-2: one blank line between successful steps. _tlog's auto-blank
        is suppressed inside workflow context, so this is the only spacing."""
        try:
            from core.signals import signals
            signals.terminal_line_ready.emit("")
        except Exception:
            pass

    def _run_from_impl(start_idx: int) -> dict:
        for idx in range(start_idx, total):
            _yield_ui()
            step_n = idx + 1
            step = steps[idx]
            if isinstance(step, str):
                # Brain resolution can transiently return `unknown` when
                # Anthropic is overloaded (HTTP 529) — a single retry with
                # a small delay catches the common case. Without this,
                # a 2-second blip at fire-time kills the whole routine.
                parsed = _ask_claude_step(step, step_n)
                if parsed.get("intent") == "unknown":
                    # NB: do NOT `import time as _time` here — a local import
                    # would make `_time` function-local to _run_from and shadow
                    # the enclosing import (line ~180), making the
                    # `_time.perf_counter()` below raise UnboundLocalError for
                    # every structured step. Use the closed-over `_time`.
                    _tlog(f"… retrying step {step_n} after brain returned 'unknown'")
                    _time.sleep(1.2)
                    parsed = _ask_claude_step(step, step_n)
                if parsed.get("intent") == "unknown":
                    state["results"].append(f"Step {step_n}: FAIL — could not parse '{step}'")
                    state["all_ok"] = False
                    _tlog(f"✗ failed at step {step_n}: could not parse {step!r}")
                    return _err("\n".join(state["results"]))
                step = parsed

            try:
                from core.signals import signals
                signals.status_changed.emit(
                    f"Automation: step {step_n}/{total} — {step.get('action', '').replace('_', ' ')}"
                )
            except Exception:
                pass

            # Keep executor dispatch on the owner thread; browser/session backends
            # (Playwright sync API) are thread-affine and fail if switched.
            # UX-2: enter/leave the workflow context so leaf-handler _tlog
            # calls inside dispatch() auto-indent.
            _enter_workflow_step()
            _t0 = _time.perf_counter()
            try:
                sub = dispatch({
                    "intent":     step.get("intent", "unknown"),
                    "action":     step.get("action", ""),
                    "parameters": step.get("parameters", {}),
                    "requires_confirmation": False,
                }, confirmed=False)
            finally:
                _leave_workflow_step()
            _elapsed = _time.perf_counter() - _t0
            _yield_ui()

            # Record latency for saved workflows only; inline workflows have
            # no stable id to key on. Skip when the step needs confirmation
            # (no real execution happened yet) or when it failed (failure
            # times shouldn't pollute the rolling avg).
            if (
                workflow_id
                and not sub.get("needs_confirmation")
                and sub.get("success")
            ):
                workflow_metrics.record(workflow_id, idx, _elapsed)

            if sub.get("needs_confirmation"):
                pending = get_pending_confirmation()
                if not pending or not pending.get("fn"):
                    return sub
                original_fn = pending["fn"]
                prompt = pending["prompt"]

                def _resume_impl(
                    original_fn=original_fn,
                    prompt=prompt,
                    step_n=step_n,
                    step=step,
                    idx=idx,
                ) -> dict:
                    _yield_ui()
                    # UX-2: re-enter workflow context so leaf _tlog calls
                    # in the deferred fn indent like the eager path.
                    _enter_workflow_step()
                    # Time only original_fn() — the user's pre-confirm wait
                    # is not step execution time.
                    _t0_resume = _time.perf_counter()
                    try:
                        first = original_fn()
                    finally:
                        _leave_workflow_step()
                    _elapsed_resume = _time.perf_counter() - _t0_resume
                    _yield_ui()
                    _append_step_result(step_n, first)
                    if not first.get("success"):
                        state["all_ok"] = False
                        _tlog(f"✗ failed at step {step_n}: {first.get('error') or first.get('output') or 'step failed'}")
                        return _err("\n".join(state["results"]))
                    if workflow_id:
                        workflow_metrics.record(workflow_id, idx, _elapsed_resume)
                    _absorb_step_into_state(step, first)
                    _between_step_blank()
                    return _run_from(idx + 1)

                def _resume_after_confirm() -> dict:
                    # R3-2: count the resume frame as in-flight too — its prelude
                    # (_yield_ui + original_fn) pumps processEvents before it
                    # recurses into _run_from.
                    global _workflow_depth
                    _workflow_depth += 1
                    try:
                        return _resume_impl()
                    finally:
                        _workflow_depth -= 1

                # Re-register pending confirmation with a continuation closure:
                # UI confirm executes current step, then resumes later steps.
                return request_confirmation(prompt, _resume_after_confirm)

            _append_step_result(step_n, sub)
            if sub.get("success"):
                _absorb_step_into_state(step, sub)
                _between_step_blank()
            else:
                state["all_ok"] = False
                if sub.get("quit_application"):
                    state["quit_application"] = True
                _tlog(f"✗ failed at step {step_n}: {sub.get('error') or sub.get('output') or 'step failed'}")
                return _err("\n".join(state["results"]))

        _tlog(f"✓ all {total} step{'s' if total != 1 else ''} complete")
        out: dict = _ok("\n".join(state["results"]))
        if state["last_step_intent"] and state["last_step_action"]:
            out["last_step_intent"] = state["last_step_intent"]
            out["last_step_action"] = state["last_step_action"]
        if state["last_python_file"]:
            out["last_python_file"] = state["last_python_file"]
        if state["last_directory"]:
            out["last_directory"] = state["last_directory"]
        if state["quit_application"]:
            out["quit_application"] = True
        return out

    def _run_from(start_idx: int) -> dict:
        # R3-1/R3-2: mark the workflow in-flight for the whole _run_from span so
        # main.py rejects re-entrant commands / cron fires during the
        # processEvents() pump. Counter handles the _resume → _run_from nesting.
        global _workflow_depth
        _workflow_depth += 1
        try:
            return _run_from_impl(start_idx)
        finally:
            _workflow_depth -= 1

    out = _run_from(0)
    if out.get("needs_confirmation"):
        return out
    if workflow_id and out.get("success"):
        workflow_library.mark_run(workflow_id)
    return out
