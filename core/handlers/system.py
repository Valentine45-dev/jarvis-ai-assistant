"""Handlers: system_control (volume, brightness, screenshot, power)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from core.handlers.shared import _OS, _ok, _err, _coerce_volume_level, request_confirmation
from core.handlers.paths import _resolve_screenshot_path, _find_folder
from core import computer_control as cc


def _handle_brightness(action: str, level: int | None) -> dict:
    def _target(current: int) -> int:
        if level is not None:
            return max(0, min(100, int(level)))
        step = 10
        return min(100, current + step) if action == "brightness_up" else max(0, current - step)

    try:
        import screen_brightness_control as sbc  # type: ignore
        raw = sbc.get_brightness()
        current = int((raw[0] if isinstance(raw, list) else raw) or 50)
        t = _target(current)
        sbc.set_brightness(t)
        return _ok(f"Brightness set to {t}%")
    except ImportError:
        pass
    except Exception as exc:
        return _err(f"Brightness error: {exc}")

    if _OS == "windows":
        t = _target(50)
        ps_cmd = (
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1, {t})"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, timeout=8,
            )
            if r.returncode == 0:
                return _ok(f"Brightness set to {t}%")
            stderr = (r.stderr or b"").decode(errors="replace").strip()
            return _err(f"Brightness unavailable: {stderr or 'WMI call failed'}")
        except Exception as exc:
            return _err(f"Brightness control failed: {exc}")

    return _err("Brightness control not supported on this platform")


def _handle_system_control(action: str, params: dict) -> dict:
    if action in ("volume_up", "volume_down"):
        return cc.set_volume(action, level=_coerce_volume_level(params))
    if action == "volume_mute":
        return cc.set_volume("volume_mute", level=None)

    if action == "screenshot":
        save_param = params.get("save_path") or params.get("folder") or None
        resolved, missing_folder = _resolve_screenshot_path(save_param)

        if missing_folder:
            def _create_and_screenshot():
                folder = _find_folder(missing_folder)
                if not folder:
                    folder = Path.home() / "Desktop"
                path = str(folder / f"JARVIS_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                return cc.screenshot(path=path)
            from core.personality import ask as _ask
            return request_confirmation(
                _ask("folder_not_found", missing_folder),
                _create_and_screenshot,
            )

        region = params.get("region")
        result = cc.screenshot(path=resolved, region=region)
        if result["success"]:
            result["output"] = Path(resolved).name
        return result

    if action == "lock_screen":
        return cc.lock_screen()

    if action in ("brightness_up", "brightness_down"):
        level = _coerce_volume_level(params)
        return _handle_brightness(action, level)

    if action in ("shutdown", "restart", "sleep"):
        _win_root = os.environ.get("SystemRoot", r"C:\Windows")
        _win_shutdown = os.path.join(_win_root, "System32", "shutdown.exe")
        cmds = {
            "windows": {
                "shutdown": [_win_shutdown, "/s", "/t", "5"],
                "restart":  [_win_shutdown, "/r", "/t", "5"],
                "sleep":    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            },
            "darwin": {
                "shutdown": ["sudo", "shutdown", "-h", "now"],
                "restart":  ["sudo", "shutdown", "-r", "now"],
                "sleep":    ["pmset", "sleepnow"],
            },
            "linux": {
                "shutdown": ["shutdown", "-h", "now"],
                "restart":  ["shutdown", "-r", "now"],
                "sleep":    ["systemctl", "suspend"],
            },
        }
        cmd = cmds.get(_OS, cmds["linux"]).get(action)
        if cmd:
            subprocess.Popen(cmd)
        return _ok(f"Executing: {action}")

    return _ok(f"System: {action}")
