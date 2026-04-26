"""
Deep OS control layer.
PyAutoGUI  — mouse / keyboard automation
Pytesseract — OCR / read_screen
Windows ctypes — screen lock, system calls
All deps are lazy-imported so the module loads cleanly even when absent.
Every public function returns {"success": bool, "output": str, "error": str}.
"""

from __future__ import annotations

import platform
from pathlib import Path

_OS = platform.system().lower()


# ── Result helpers ────────────────────────────────────────────────────────────

def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}

def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


# ── Lazy import guards ────────────────────────────────────────────────────────

def _pag():
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        return pyautogui
    except ImportError:
        return None

def _pyt():
    try:
        import pytesseract
        return pytesseract
    except ImportError:
        return None


# ── KEYBOARD ──────────────────────────────────────────────────────────────────

def type_text(text: str, delay: float = 0.02) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        pag.typewrite(text, interval=delay)
        return _ok(f"Typed: {text[:40]}")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def press_key(combo: str) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        if "+" in combo:
            pag.hotkey(*combo.lower().split("+"))
        else:
            pag.press(combo.lower())
        return _ok(f"Pressed: {combo}")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


# ── MOUSE ─────────────────────────────────────────────────────────────────────

def move(x: int, y: int) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        pag.moveTo(x, y, duration=0.3)
        return _ok(f"Mouse moved to ({x}, {y})")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def click(x=None, y=None, button: str = "left") -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        if x is not None and y is not None:
            pag.click(x, y, button=button)
        else:
            pag.click(button=button)
        loc = f" at ({x}, {y})" if x is not None else ""
        return _ok(f"Clicked ({button}){loc}")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def double_click(x=None, y=None) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        pag.doubleClick(x, y) if x is not None and y is not None else pag.doubleClick()
        return _ok("Double-clicked")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def right_click(x=None, y=None) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        pag.rightClick(x, y) if x is not None and y is not None else pag.rightClick()
        return _ok("Right-clicked")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def scroll(direction: str = "up", amount: int = 3) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        clicks = amount if direction == "up" else -amount
        pag.scroll(clicks)
        return _ok(f"Scrolled {direction} {amount}")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def drag(from_x: int, from_y: int, to_x: int, to_y: int) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        pag.moveTo(from_x, from_y)
        pag.dragTo(to_x, to_y, duration=0.4, button="left")
        return _ok(f"Dragged ({from_x},{from_y}) → ({to_x},{to_y})")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


# ── SCREEN ────────────────────────────────────────────────────────────────────

def screenshot(path: str | None = None, region: dict | None = None) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        save_path = path or str(Path.home() / "Desktop" / "jarvis_screenshot.png")
        if region:
            img = pag.screenshot(
                region=(region["x"], region["y"], region["width"], region["height"])
            )
        else:
            img = pag.screenshot()
        img.save(save_path)
        return _ok(f"Screenshot saved: {save_path}")
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def ocr_screen(region: dict | None = None) -> dict:
    pyt = _pyt()
    pag = _pag()
    if pyt is None:
        return _err("pytesseract not installed — run: uv add pytesseract")
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        if region:
            img = pag.screenshot(
                region=(region["x"], region["y"], region["width"], region["height"])
            )
        else:
            img = pag.screenshot()
        text = pyt.image_to_string(img)
        return _ok(text[:2000])
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        msg = str(exc)
        if "tesseract" in msg.lower():
            return _err(
                "Tesseract binary not found — "
                "download from: github.com/UB-Mannheim/tesseract/wiki"
            )
        return _err(msg)


# ── SYSTEM ────────────────────────────────────────────────────────────────────

def set_volume(action: str, level: int | None = None) -> dict:
    # pycaw gives precise Windows volume control
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol       = cast(interface, POINTER(IAudioEndpointVolume))

        if level is not None:
            scalar = max(0.0, min(1.0, level / 100.0))
            vol.SetMasterVolumeLevelScalar(scalar, None)
            return _ok(f"{level}%")

        current = int(vol.GetMasterVolumeLevelScalar() * 100)
        if action == "volume_mute":
            is_muted = bool(vol.GetMute())
            vol.SetMute(not is_muted, None)
            return _ok("Unmuted" if is_muted else "Muted")
        if action == "volume_up":
            new_level = min(100, current + 10)
            vol.SetMasterVolumeLevelScalar(new_level / 100.0, None)
            return _ok(f"{new_level}%")
        if action == "volume_down":
            new_level = max(0, current - 10)
            vol.SetMasterVolumeLevelScalar(new_level / 100.0, None)
            return _ok(f"{new_level}%")
    except ImportError:
        pass  # fall through to pyautogui media keys
    except Exception:
        pass

    # Fallback: pyautogui media keys (each press ≈ 2% on Windows)
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        key_map = {
            "volume_up":   "volumeup",
            "volume_down": "volumedown",
            "volume_mute": "volumemute",
        }
        key = key_map.get(action, "volumeup")
        for _ in range(5):    # 5 presses ≈ 10% change
            pag.press(key)
        return _ok(action.replace("_", " ").title())
    except pag.FailSafeException:
        return _err("FAILSAFE triggered — mouse moved to corner")
    except Exception as exc:
        return _err(str(exc))


def lock_screen() -> dict:
    try:
        if _OS == "windows":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif _OS == "darwin":
            import subprocess
            subprocess.Popen([
                "/System/Library/CoreServices/Menu Extras/User.menu"
                "/Contents/Resources/CGSession",
                "-suspend",
            ])
        else:
            import subprocess
            subprocess.Popen(["loginctl", "lock-session"])
        return _ok("Screen locked")
    except Exception as exc:
        return _err(str(exc))


# ── CLIPBOARD ─────────────────────────────────────────────────────────────────

def get_clipboard() -> dict:
    try:
        import pyperclip
        return _ok(pyperclip.paste()[:500])
    except ImportError:
        return _err("pyperclip not installed — run: uv add pyperclip")
    except Exception as exc:
        return _err(str(exc))


def set_clipboard(text: str) -> dict:
    try:
        import pyperclip
        pyperclip.copy(text)
        return _ok(f"Clipboard set: {text[:40]}")
    except ImportError:
        return _err("pyperclip not installed — run: uv add pyperclip")
    except Exception as exc:
        return _err(str(exc))
