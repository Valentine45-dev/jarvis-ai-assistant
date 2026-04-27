"""Handlers: type_text, control_mouse."""

from __future__ import annotations

from core.handlers.shared import _err
from core import computer_control as cc


def _handle_type_text(action: str, params: dict) -> dict:
    if action == "press_key":
        return cc.press_key(params.get("key", ""))
    text = params.get("text", "")
    if action == "type_paste":
        r = cc.set_clipboard(text)
        return r if not r["success"] else cc.press_key("ctrl+v")
    return cc.type_text(text, float(params.get("delay", 0.02)))


def _handle_control_mouse(action: str, params: dict) -> dict:
    x, y = params.get("x"), params.get("y")
    if action == "move_mouse":
        return cc.move(x, y)
    if action == "click":
        return cc.click(x, y, params.get("button", "left"))
    if action == "double_click":
        return cc.double_click(x, y)
    if action == "right_click":
        return cc.right_click(x, y)
    if action == "scroll":
        return cc.scroll(params.get("direction", "up"), int(params.get("amount", 3)))
    if action == "drag":
        return cc.drag(params["from_x"], params["from_y"], params["to_x"], params["to_y"])
    return _err(f"Unknown mouse action: {action}")
