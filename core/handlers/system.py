"""Handlers: system_control (volume, brightness, screenshot, power)."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from core.handlers.shared import _OS, _ok, _err, _coerce_volume_level, request_confirmation
from core.handlers.paths import _resolve_screenshot_path, _find_folder
from core import computer_control as cc


def _run_powershell(cmd: str, timeout: int = 12) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)
    out = (r.stdout or b"").decode(errors="replace").strip()
    err = (r.stderr or b"").decode(errors="replace").strip()
    if r.returncode != 0:
        return False, err or out or f"PowerShell failed with exit {r.returncode}"
    return True, out or err or ""


def _toggle_wifi_windows() -> dict:
    probe = (
        "$a = Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue;"
        "if (-not $a) { $a = Get-NetAdapter | Where-Object { $_.Name -match 'Wi-?Fi|Wireless|WLAN' } | Select-Object -First 1 };"
        "if (-not $a) { Write-Output '__NO_WIFI__'; exit 0 };"
        "Write-Output ($a.Name + '|' + $a.Status)"
    )
    ok, out = _run_powershell(probe)
    if not ok:
        return _err(f"Wi-Fi probe failed: {out}")
    if "__NO_WIFI__" in out:
        return _err("No Wi-Fi adapter found")

    adapter_name, _, status = out.partition("|")
    adapter_name = (adapter_name or "Wi-Fi").strip()
    status = status.strip().lower()
    should_enable = status in ("disconnected", "disabled", "not present", "unknown")

    cmd = (
        f"Enable-NetAdapter -Name '{adapter_name}' -Confirm:$false"
        if should_enable
        else f"Disable-NetAdapter -Name '{adapter_name}' -Confirm:$false"
    )
    ok2, out2 = _run_powershell(cmd)
    if not ok2:
        return _err(f"Wi-Fi toggle failed: {out2}")
    return _ok("Wi-Fi enabled" if should_enable else "Wi-Fi disabled")


def _toggle_bluetooth_windows() -> dict:
    ps = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null;"
        "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
        "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 })[0];"
        "$accessTask = $asTask.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @([Windows.Devices.Radios.Radio]::RequestAccessAsync()));"
        "$accessTask.Wait(-1) | Out-Null;"
        "$access = $accessTask.Result;"
        "if ($access -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) { Write-Output '__ACCESS_DENIED__'; exit 0 };"
        "$radiosTask = $asTask.MakeGenericMethod([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]).Invoke($null, @([Windows.Devices.Radios.Radio]::GetRadiosAsync()));"
        "$radiosTask.Wait(-1) | Out-Null;"
        "$radios = $radiosTask.Result;"
        "$bt = $radios | Where-Object { $_.Kind -eq [Windows.Devices.Radios.RadioKind]::Bluetooth } | Select-Object -First 1;"
        "if (-not $bt) { Write-Output '__NO_BT__'; exit 0 };"
        "$target = if ($bt.State -eq [Windows.Devices.Radios.RadioState]::On) { [Windows.Devices.Radios.RadioState]::Off } else { [Windows.Devices.Radios.RadioState]::On };"
        "$setTask = $asTask.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @($bt.SetStateAsync($target)));"
        "$setTask.Wait(-1) | Out-Null;"
        "$setRes = $setTask.Result;"
        "if ($setRes -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) { Write-Output '__SET_DENIED__'; exit 0 };"
        "if ($target -eq [Windows.Devices.Radios.RadioState]::On) { Write-Output 'Bluetooth enabled' } else { Write-Output 'Bluetooth disabled' }"
    )
    ok, out = _run_powershell(ps, timeout=20)
    if not ok:
        return _err(f"Bluetooth toggle failed: {out}")
    if "__ACCESS_DENIED__" in out:
        return _err("Bluetooth access denied by Windows")
    if "__NO_BT__" in out:
        return _err("No Bluetooth radio found")
    if "__SET_DENIED__" in out:
        return _err("Windows denied Bluetooth state change")
    return _ok(out or "Bluetooth toggled")


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
    if action in ("volume_mute", "volume_unmute"):
        return cc.set_volume(action, level=None)

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

    if action == "wifi_toggle":
        if _OS == "windows":
            return _toggle_wifi_windows()
        return _err("Wi-Fi toggle is currently supported only on Windows")

    if action == "bluetooth_toggle":
        if _OS == "windows":
            return _toggle_bluetooth_windows()
        return _err("Bluetooth toggle is currently supported only on Windows")

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
