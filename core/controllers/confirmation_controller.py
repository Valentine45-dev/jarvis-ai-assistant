"""Confirmation flow decision helpers for JarvisWindow."""

from __future__ import annotations


class ConfirmationController:
    DEFAULT_PROMPT = "Awaiting your confirmation, sir."
    CANCEL_MESSAGE = "Understood, standing down, sir."

    def needs_followup_confirmation(self, resolved: dict) -> bool:
        return bool((resolved or {}).get("needs_confirmation"))

    def prompt_from_result(self, resolved: dict) -> str:
        return str((resolved or {}).get("output") or self.DEFAULT_PROMPT)

    def final_display_response(self, resolved: dict) -> str:
        out = str((resolved or {}).get("output") or "").strip()
        if out:
            return out
        return "Done, sir." if bool((resolved or {}).get("success")) else self.CANCEL_MESSAGE

    def final_hud_status(self, resolved: dict) -> str:
        return "CONFIRMED" if bool((resolved or {}).get("success")) else "CANCELLED"

    def final_history_status(self, resolved: dict) -> str:
        return "success" if bool((resolved or {}).get("success")) else "error"

    def final_toast_kind(self, resolved: dict) -> str:
        return "success" if bool((resolved or {}).get("success")) else "info"
