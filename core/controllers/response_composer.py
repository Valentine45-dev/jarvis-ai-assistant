"""Pure response composition for execution results."""

from __future__ import annotations


def compose_execution_response(
    *,
    intent: str,
    result: dict,
    exec_out: dict,
    resp: str,
    action_intents: frozenset,
    factual_actions: frozenset,
) -> tuple[str, str | None, str]:
    """Return (primary, follow, display_resp) without touching UI state."""
    from core.personality import say as personality_say
    from core.responders.assembler import responder

    exec_ok = bool(exec_out.get("success"))
    last_step: tuple[str, str] | None = None
    li = exec_out.get("last_step_intent")
    la = exec_out.get("last_step_action")
    if li and la:
        last_step = (str(li), str(la))

    primary = ""
    follow: str | None = None

    if intent in action_intents:
        primary, follow = responder.build(
            intent,
            result.get("action", ""),
            exec_ok,
            resp,
            exec_out.get("output", ""),
            exec_out.get("error", ""),
            params=result.get("parameters", {}),
            last_step=last_step,
        )
        if intent == "automation_task" and result.get("action") == "run_workflow":
            follow = None
        display_resp = f"{primary}\n{follow}" if follow else primary
    elif intent == "jarvis_meta":
        action_name = result.get("action", "")
        if (
            action_name in ("quit_application", "close_jarvis")
            and exec_out.get("quit_application")
        ):
            display_resp = (resp or "").strip() or (
                "Closing JARVIS — catch you later, Valentine."
            )
        elif action_name in factual_actions and exec_out.get("output"):
            status = "ok" if exec_out["success"] else "err"
            display_resp = personality_say(
                intent, action_name, status,
                exec_out.get("output", ""),
                exec_out.get("error", ""),
            )
        elif not exec_out.get("success"):
            display_resp = personality_say(
                intent, action_name, "err",
                exec_out.get("output", ""),
                exec_out.get("error", ""),
            )
        elif action_name in ("change_voice", "change_theme") and exec_out.get("output"):
            # Speak the handler's OWN line, not the brain's pre-execution resp.
            # change_voice needs it (audible proof in the new voice); change_theme
            # needs it so the honest "set to X — restart to apply" is spoken
            # instead of the brain's optimistic "going green" (P7 fake-success #3).
            display_resp = exec_out["output"]
        elif action_name == "conversational" and exec_out.get("output"):
            display_resp = exec_out["output"]
        else:
            display_resp = resp
        primary = display_resp
    else:
        display_resp = resp
        primary = display_resp

    if not primary and display_resp is not None:
        primary = display_resp
    return primary, follow, display_resp
