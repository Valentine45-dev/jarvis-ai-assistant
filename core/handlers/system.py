"""Handlers: system_control (volume, brightness, screenshot, power)."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from config.settings import config
from core.handlers.shared import _OS, _ok, _err, _coerce_volume_level, request_confirmation
from core.handlers.paths import _resolve_screenshot_path, _find_folder
from core import computer_control as cc


def _is_access_denied(text: str) -> bool:
    s = (text or "").lower()
    return (
        "access is denied" in s
        or "permission denied" in s
        or "requires elevation" in s
        or "not have sufficient privilege" in s
    )


def _compact_powershell_error(text: str, fallback: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return fallback
    if _is_access_denied(raw):
        return "Access denied by Windows"
    first = raw.splitlines()[0].strip()
    if not first:
        return fallback
    if len(first) > 180:
        first = first[:177].rstrip() + "..."
    return first


def _run_powershell(cmd: str, timeout: int = 12, mta: bool = False) -> tuple[bool, str]:
    # -Mta is required for WinRT async APIs: the default STA apartment causes .Wait(-1)
    # to deadlock because WinRT completions need to post back to the STA message pump,
    # which is blocked by the wait itself.
    flags = ["-NonInteractive", "-ExecutionPolicy", "Bypass"]
    if mta:
        flags.insert(0, "-Mta")
    try:
        r = subprocess.run(
            ["powershell"] + flags + ["-Command", cmd],
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
        short = _compact_powershell_error(out, "Unable to inspect Wi-Fi adapter state")
        if _is_access_denied(out):
            return _err("Wi-Fi toggle requires Administrator privileges on Windows.")
        return _err(f"Wi-Fi probe failed: {short}")
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
        short = _compact_powershell_error(out2, "Unable to toggle Wi-Fi adapter")
        if _is_access_denied(out2):
            return _err("Wi-Fi toggle requires Administrator privileges on Windows.")
        return _err(f"Wi-Fi toggle failed: {short}")
    return _ok("Wi-Fi enabled" if should_enable else "Wi-Fi disabled")


def _toggle_bluetooth_windows() -> dict:
    if config.debug_mode:
        print("[bt] toggle start: trying WinRT Radio API (MTA)")
    # Must run in MTA (-Mta) — WinRT async tasks deadlock when .Wait(-1) is called on an
    # STA thread because WinRT completions need to post back to the STA message pump.
    ps = (
        "try {"
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null;"
        "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null;"
        "$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
        "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethodDefinition -and $_.ReturnType.IsGenericType })[0];"
        "$accessTask = $asTask.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @([Windows.Devices.Radios.Radio]::RequestAccessAsync()));"
        "$accessTask.Wait(-1) | Out-Null;"
        "$access = $accessTask.Result;"
        "if ($access -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) { Write-Output ('__ACCESS_DENIED__|' + $access.ToString()); exit 0 };"
        "$radiosTask = $asTask.MakeGenericMethod([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]).Invoke($null, @([Windows.Devices.Radios.Radio]::GetRadiosAsync()));"
        "$radiosTask.Wait(-1) | Out-Null;"
        "$radios = $radiosTask.Result;"
        "$bt = $radios | Where-Object { $_.Kind -eq [Windows.Devices.Radios.RadioKind]::Bluetooth } | Select-Object -First 1;"
        "if (-not $bt) { Write-Output '__NO_BT__'; exit 0 };"
        "$target = if ($bt.State -eq [Windows.Devices.Radios.RadioState]::On) { [Windows.Devices.Radios.RadioState]::Off } else { [Windows.Devices.Radios.RadioState]::On };"
        "$setTask = $asTask.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @($bt.SetStateAsync($target)));"
        "$setTask.Wait(-1) | Out-Null;"
        "$setRes = $setTask.Result;"
        "if ($setRes -ne [Windows.Devices.Radios.RadioAccessStatus]::Allowed) { Write-Output ('__SET_DENIED__|' + $setRes.ToString()); exit 0 };"
        "if ($target -eq [Windows.Devices.Radios.RadioState]::On) { Write-Output 'Bluetooth enabled' } else { Write-Output 'Bluetooth disabled' }"
        "} catch { Write-Output ('__PS_ERROR__|' + $_.Exception.Message); exit 0 }"
    )
    ok, out = _run_powershell(ps, timeout=20, mta=True)
    if not ok:
        if config.debug_mode:
            print(f"[bt] WinRT path failed: {out}")
        short = _compact_powershell_error(out, "Unable to toggle Bluetooth")
        if _is_access_denied(out):
            return _err("Bluetooth toggle requires Administrator privileges on Windows.")
        return _err(f"Bluetooth toggle failed: {short}")
    if "__ACCESS_DENIED__" in out or "__SET_DENIED__" in out or "__PS_ERROR__" in out:
        detail = out.split("|", 1)[1].strip() if "|" in out else out
        if config.debug_mode:
            sentinel = out.split("|")[0].strip("_")
            print(f"[bt] WinRT {sentinel}: {detail}; trying PnP fallback")
        fb = _toggle_bluetooth_windows_fallback_pnp()
        if fb.get("success"):
            return fb
        if config.debug_mode:
            print("[bt] PnP fallback failed; trying UI fallback")
        fb = _toggle_bluetooth_windows_fallback_ui()
        if fb.get("success"):
            return fb
        if "__PS_ERROR__" in out:
            return _err(f"Bluetooth toggle failed: {_compact_powershell_error(detail, 'WinRT error')}")
        return _err("Bluetooth toggle requires Administrator privileges on Windows.")
    if "__NO_BT__" in out:
        return _err("No Bluetooth radio found")
    if config.debug_mode:
        print(f"[bt] WinRT success: {out}")
    return _ok(out or "Bluetooth toggled")


def _toggle_bluetooth_windows_fallback_pnp() -> dict:
    """Fallback: toggle a Bluetooth PnP device (often requires elevation)."""
    ps = (
        "$devs = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue;"
        "if (-not $devs) { Write-Output '__NO_BT__'; exit 0 };"
        "$on = $devs | Where-Object { $_.Status -eq 'OK' } | Select-Object -First 1;"
        "if ($on) {"
        "  try { Disable-PnpDevice -InstanceId $on.InstanceId -Confirm:$false -ErrorAction Stop | Out-Null; Write-Output '__PNP_DISABLED__'; exit 0 }"
        "  catch { Write-Output ('__PNP_DISABLE_FAIL__|' + $_.Exception.Message); exit 0 }"
        "}"
        "$off = $devs | Select-Object -First 1;"
        "try { Enable-PnpDevice -InstanceId $off.InstanceId -Confirm:$false -ErrorAction Stop | Out-Null; Write-Output '__PNP_ENABLED__'; exit 0 }"
        "catch { Write-Output ('__PNP_ENABLE_FAIL__|' + $_.Exception.Message); exit 0 }"
    )
    ok, out = _run_powershell(ps, timeout=20)
    if not ok:
        if config.debug_mode:
            print(f"[bt] PnP exec failed: {out}")
        short = _compact_powershell_error(out, "Unable to access Bluetooth PnP devices")
        if _is_access_denied(out):
            return _err("Bluetooth toggle requires Administrator privileges on Windows.")
        return _err(f"Bluetooth PnP fallback failed: {short}")
    if "__PNP_DISABLED__" in out:
        if config.debug_mode:
            print("[bt] PnP success: Bluetooth disabled")
        return _ok("Bluetooth disabled")
    if "__PNP_ENABLED__" in out:
        if config.debug_mode:
            print("[bt] PnP success: Bluetooth enabled")
        return _ok("Bluetooth enabled")
    if "__NO_BT__" in out:
        return _err("No Bluetooth device found")
    if "__PNP_DISABLE_FAIL__" in out or "__PNP_ENABLE_FAIL__" in out:
        _msg = out.split("|", 1)[1].strip() if "|" in out else "permission denied"
        if config.debug_mode:
            print(f"[bt] PnP denied: {_msg}")
        if _is_access_denied(_msg):
            return _err("Bluetooth toggle requires Administrator privileges on Windows.")
        _msg = _compact_powershell_error(_msg, "Bluetooth device toggle failed")
        return _err(f"Bluetooth device toggle failed: {_msg}")
    if config.debug_mode:
        print(f"[bt] PnP no state change: {out}")
    return _err("Bluetooth PnP fallback did not change state")


def _toggle_bluetooth_windows_fallback_ui() -> dict:
    """Best-effort fallback: open Quick Settings then use UIAutomation to click the Bluetooth tile.

    UIAutomation finds the Bluetooth button by name so it works regardless of tile
    order or Quick Settings layout customisation. Both InvokePattern and TogglePattern
    are tried since Windows uses different patterns across versions.
    """
    try:
        if config.debug_mode:
            print("[bt] UI fallback: opening Quick Settings via Win+A")
        r = cc.press_key("win+a")
        if not r.get("success"):
            return _err("Bluetooth fallback failed to open Quick Settings")
        time.sleep(0.6)  # wait for the panel to fully render

        ps = (
            "Add-Type -AssemblyName UIAutomationClient | Out-Null;"
            "Add-Type -AssemblyName UIAutomationTypes | Out-Null;"
            "$root = [System.Windows.Automation.AutomationElement]::RootElement;"
            # Search all Button/CheckBox elements whose name contains "bluetooth" — exact
            # match fails when Windows appends state text like "Bluetooth Not connected".
            "$btnCond = New-Object System.Windows.Automation.PropertyCondition("
            "  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,"
            "  [System.Windows.Automation.ControlType]::Button);"
            "$buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond);"
            "$el = $null;"
            "foreach ($b in $buttons) {"
            "  try { if ($b.Current.Name -match '(?i)bluetooth') { $el = $b; break } } catch {}"
            "};"
            "if (-not $el) { Write-Output '__NOT_FOUND__'; exit 0 };"
            "try {"
            "  $inv = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern);"
            "  $inv.Invoke(); Write-Output 'toggled_invoke'; exit 0"
            "} catch {};"
            "try {"
            "  $tog = $el.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern);"
            "  $tog.Toggle(); Write-Output 'toggled_toggle'; exit 0"
            "} catch {};"
            "Write-Output '__NO_PATTERN__'"
        )
        ok, out = _run_powershell(ps, timeout=8)
        if config.debug_mode:
            print(f"[bt] UIA result: ok={ok} out={out!r}")

        time.sleep(0.2)
        cc.press_key("escape")

        if ok and ("toggled_invoke" in out or "toggled_toggle" in out):
            return _ok("Bluetooth toggled via Quick Settings")
        if "__NOT_FOUND__" in out:
            return _err("Bluetooth tile not found in Quick Settings")
        if "__NO_PATTERN__" in out:
            return _err("Bluetooth tile found but could not be activated")
        return _err(f"Bluetooth UI automation failed: {out}")
    except Exception as exc:
        return _err(f"Bluetooth fallback failed: {exc}")


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
                # SetSuspendState(Hibernate, ForceCritical, DisableWakeEvent):
                # ForceCritical=1 may close apps without warning — use 0,0,0.
                "sleep":    ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,0,0"],
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
