"""Handler: automation_task — workflow CRUD and run_workflow step execution."""

from __future__ import annotations

from pathlib import Path

from core.handlers.shared import _ok, _err

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

_BLOCKED_INTENTS: frozenset[str] = frozenset()  # code_execution is now allowed in workflows

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
})


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
        if not task_name:
            return _err("No task_name provided for workflow creation.")
        if not isinstance(steps, list) or not steps:
            return _err("Steps must be a non-empty list.")
        slug = task_name.lower().replace(" ", "_")
        if workflow_library.get(slug) is not None:
            return _err(f"Workflow '{task_name}' already exists.")
        for i, step in enumerate(steps, 1):
            if isinstance(step, str):
                continue  # validated at runtime when ask_claude parses it
            if not isinstance(step, dict):
                return _err(f"Step {i} must be a dict or string.")
            s_intent = step.get("intent", "")
            s_action = step.get("action", "")
            if not s_intent:
                return _err(f"Step {i} is missing 'intent'.")
            if s_intent in _BLOCKED_INTENTS:
                return _err(f"Step {i} uses blocked intent '{s_intent}'.")
            if s_intent not in _KNOWN_STEP_INTENTS:
                return _err(f"Step {i} has unrecognised intent '{s_intent}'.")
            if (s_intent, s_action) in _DANGEROUS_STEPS:
                return _err(f"Step {i} contains dangerous action '{s_action}'.")
        wf = {
            "id": slug, "name": task_name, "trigger": trigger,
            "enabled": True, "last_run": "", "steps": steps,
        }
        workflow_library.add(wf)
        return _ok(f"Workflow '{task_name}' created with {len(steps)} step(s).")

    if action == "remove_workflow":
        task_name = params.get("task_name", "")
        if not task_name:
            return _err("No task_name provided.")
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow '{task_name}' not found.")
        workflow_library.remove(wf["id"])
        return _ok(f"Workflow '{wf['name']}' deleted.")

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
    from core.executor import dispatch  # late import — executor is fully loaded by runtime
    from core.handlers.shared import get_pending_confirmation, request_confirmation

    steps     = params.get("steps", [])
    task_name = params.get("task_name", "")
    workflow_id: str = ""

    # If task_name resolves to a saved workflow, always prefer its persisted
    # step list over any inline steps from model output.
    if task_name:
        wf = workflow_library.get(task_name)
        if wf is not None:
            if not wf.get("enabled", True):
                return _err(f"Workflow '{wf['name']}' is disabled.")
            steps       = wf.get("steps", [])
            workflow_id = wf.get("id", "")
        elif not steps:
            return _err(f"Workflow not found: {task_name!r}")

    if not steps:
        return _err("No steps provided in automation task")

    for step in steps:
        if isinstance(step, str):
            continue  # string steps are parsed at runtime
        intent   = step.get("intent", "")
        s_action = step.get("action", "")
        if intent in _BLOCKED_INTENTS:
            return _err(f"Workflow contains a '{intent}' step requiring manual confirmation.")
        if (intent, s_action) in _DANGEROUS_STEPS:
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

    def _run_from(start_idx: int) -> dict:
        for idx in range(start_idx, total):
            step_n = idx + 1
            step = steps[idx]
            if isinstance(step, str):
                from core.brain import ask_claude
                parsed = ask_claude(
                    step,
                    use_memory=False,
                    context={
                        "workflow_step_index": step_n,
                        "workflow_total_steps": total,
                        "workflow_last_python_file": state["last_python_file"],
                        "workflow_last_directory": state["last_directory"],
                        "workflow_last_output": state["results"][-1] if state["results"] else "",
                    },
                )
                if parsed.get("intent") == "unknown":
                    state["results"].append(f"Step {step_n}: FAIL — could not parse '{step}'")
                    state["all_ok"] = False
                    return _err("\n".join(state["results"]))
                step = parsed

            try:
                from core.signals import signals
                signals.status_changed.emit(
                    f"Automation: step {step_n}/{total} — {step.get('action', '').replace('_', ' ')}"
                )
            except Exception:
                pass

            sub = dispatch({
                "intent":     step.get("intent", "unknown"),
                "action":     step.get("action", ""),
                "parameters": step.get("parameters", {}),
                "requires_confirmation": False,
            }, confirmed=False)

            if sub.get("needs_confirmation"):
                pending = get_pending_confirmation()
                if not pending or not pending.get("fn"):
                    return sub
                original_fn = pending["fn"]
                prompt = pending["prompt"]

                def _resume_after_confirm(
                    original_fn=original_fn,
                    prompt=prompt,
                    step_n=step_n,
                    step=step,
                    idx=idx,
                ) -> dict:
                    first = original_fn()
                    _append_step_result(step_n, first)
                    if not first.get("success"):
                        state["all_ok"] = False
                        return _err("\n".join(state["results"]))

                    state["last_step_intent"] = (step.get("intent") or "").strip()
                    state["last_step_action"] = (step.get("action") or "").strip()
                    if first.get("quit_application"):
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

                    return _run_from(idx + 1)

                # Re-register pending confirmation with a continuation closure:
                # UI confirm executes current step, then resumes later steps.
                return request_confirmation(prompt, _resume_after_confirm)

            if sub.get("quit_application"):
                state["quit_application"] = True
            _append_step_result(step_n, sub)
            if sub.get("success"):
                state["last_step_intent"] = (step.get("intent") or "").strip()
                state["last_step_action"] = (step.get("action") or "").strip()
                if (
                    state["last_step_intent"] == "file_operation"
                    and state["last_step_action"] == "create_file"
                ):
                    params = step.get("parameters") or {}
                    path = str(params.get("path") or "").strip()
                    if path.lower().endswith(".py"):
                        state["last_python_file"] = path
                        state["last_directory"] = str(Path(path).parent)
            else:
                state["all_ok"] = False
                return _err("\n".join(state["results"]))

        out: dict = _ok("\n".join(state["results"]))
        if state["last_step_intent"] and state["last_step_action"]:
            out["last_step_intent"] = state["last_step_intent"]
            out["last_step_action"] = state["last_step_action"]
        if state["quit_application"]:
            out["quit_application"] = True
        return out

    out = _run_from(0)
    if out.get("needs_confirmation"):
        return out
    if workflow_id and out.get("success"):
        workflow_library.mark_run(workflow_id)
    return out
