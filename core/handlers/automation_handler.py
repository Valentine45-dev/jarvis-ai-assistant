"""Handler: automation_task — workflow CRUD and run_workflow step execution."""

from __future__ import annotations

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
            "id": slug, "name": task_name, "trigger": "Manual",
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

    steps     = params.get("steps", [])
    task_name = params.get("task_name", "")
    workflow_id: str = ""

    if task_name and not steps:
        wf = workflow_library.get(task_name)
        if wf is None:
            return _err(f"Workflow not found: {task_name!r}")
        if not wf.get("enabled", True):
            return _err(f"Workflow '{wf['name']}' is disabled.")
        steps       = wf.get("steps", [])
        workflow_id = wf.get("id", "")

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

    total   = len(steps)
    results = []
    all_ok  = True
    last_step_intent  = ""
    last_step_action  = ""
    quit_application  = False

    for i, step in enumerate(steps, 1):
        # Parse natural-language string steps at runtime
        if isinstance(step, str):
            from core.brain import ask_claude
            parsed = ask_claude(step)
            if parsed.get("intent") == "unknown":
                results.append(f"Step {i}: FAIL — could not parse '{step}'")
                all_ok = False
                break
            step = parsed

        try:
            from core.signals import signals
            signals.status_changed.emit(
                f"Automation: step {i}/{total} — {step.get('action', '').replace('_', ' ')}"
            )
        except Exception:
            pass
        sub = dispatch({
            "intent":     step.get("intent", "unknown"),
            "action":     step.get("action", ""),
            "parameters": step.get("parameters", {}),
            "requires_confirmation": False,
        })
        if sub.get("needs_confirmation"):
            return sub
        if sub.get("quit_application"):
            quit_application = True
        results.append(f"Step {i}: {'OK' if sub['success'] else 'FAIL'} — {sub['output'] or sub['error']}")
        if sub["success"]:
            last_step_intent = (step.get("intent") or "").strip()
            last_step_action = (step.get("action") or "").strip()
        if not sub["success"]:
            all_ok = False
            break

    if workflow_id and all_ok:
        workflow_library.mark_run(workflow_id)

    summary = "\n".join(results)
    if not all_ok:
        return _err(summary)
    out: dict = _ok(summary)
    if last_step_intent and last_step_action:
        out["last_step_intent"] = last_step_intent
        out["last_step_action"] = last_step_action
    if quit_application:
        out["quit_application"] = True
    return out
