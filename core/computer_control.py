"""
Deep OS control layer.
PyAutoGUI  — mouse / keyboard automation
Pytesseract — OCR / read_screen
Windows ctypes — screen lock, system calls
All deps are lazy-imported so the module loads cleanly even when absent.
Every public function returns {"success": bool, "output": str, "error": str}.
"""

from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path

_OS = platform.system().lower()

# So TESSERACT_CMD in .env is available even if this module is imported before config.settings
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass


# ── Result helpers ────────────────────────────────────────────────────────────

from core.handlers.shared import _ok, _err


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


def _resolve_tesseract_cmd(pyt) -> str | None:
    """Point pytesseract at tesseract.exe if not on PATH (common on Windows)."""
    inner = pyt.pytesseract
    for key in ("TESSERACT_CMD", "TESSERACT_PATH"):
        override = (os.getenv(key) or "").strip().strip('"')
        if override:
            ex = Path(override)
            if ex.is_file():
                inner.tesseract_cmd = str(ex)
                return str(ex)
    for name in ("tesseract", "tesseract.exe"):
        which = shutil.which(name)
        if which:
            inner.tesseract_cmd = which
            return which
    if _OS == "windows":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            ex = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if ex.is_file():
                inner.tesseract_cmd = str(ex)
                return str(ex)
    if _OS == "darwin":
        for ex in (Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract")):
            if ex.is_file():
                inner.tesseract_cmd = str(ex)
                return str(ex)
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


def _normalize_key_token(tok: str) -> str:
    """Map common STT/NL phrases to pyautogui key names (esp. Windows key)."""
    t = (tok or "").strip().lower()
    aliases = {
        "windows": "win",
        "winkey": "win",
        "lwin": "winleft",
        "rwin": "winright",
    }
    return aliases.get(t, t)


def press_key(combo: str) -> dict:
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        if "+" in combo:
            parts = [_normalize_key_token(s) for s in combo.split("+")]
            pag.hotkey(*parts)
        else:
            pag.press(_normalize_key_token(combo))
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
    if _resolve_tesseract_cmd(pyt) is None:
        return _err(
            "Tesseract OCR engine not found. Install the binary (add to PATH), or set "
            "TESSERACT_CMD in .env to the full path of tesseract.exe. "
            "Windows installer: https://github.com/UB-Mannheim/tesseract/wiki"
        )
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
                "Tesseract failed to run. Reinstall or set TESSERACT_CMD in .env to "
                "tesseract.exe — https://github.com/UB-Mannheim/tesseract/wiki"
            )
        return _err(msg)


# ── SYSTEM ────────────────────────────────────────────────────────────────────

def _osd_trigger(vol, exact_scalar: float) -> None:
    """Simulate one volume key press to wake the Windows OSD, then snap back.

    pycaw's SetMasterVolumeLevelScalar is silent (no Shell overlay). A real
    key press via SendInput goes through the Windows input pipeline and shows
    the OSD. We immediately reset to the exact scalar so the displayed value
    is correct.
    """
    if _OS != "windows":
        return
    try:
        pag = _pag()
        if pag is None:
            return
        pag.press("volumeup")                              # wakes OSD, bumps +1 step
        vol.SetMasterVolumeLevelScalar(exact_scalar, None) # snap back to exact level
    except Exception:
        pass  # OSD is cosmetic — never block the caller


def _press_mute_hotkey() -> None:
    """Send VK_VOLUME_MUTE so the OS toggles its own mute state.

    pycaw's IAudioEndpointVolume.SetMute(...) reliably corrupts the audio
    session in this process for several seconds afterwards — subsequent TTS
    playback (pyaudio/sounddevice) and STT capture both hard-crash the C
    extension. Routing through the OS hotkey path keeps our process's audio
    session untouched. pyautogui first (cross-platform key name); ctypes
    keybd_event as the bare-metal Windows fallback.
    """
    pag = _pag()
    if pag is not None:
        try:
            pag.press("volumemute")
            return
        except Exception:
            pass
    if _OS == "windows":
        try:
            import ctypes
            VK_VOLUME_MUTE = 0xAD
            KEYEVENTF_KEYUP = 0x02
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass


def set_volume(action: str, level: int | None = None) -> dict:
    # pycaw gives precise Windows volume control
    pycaw_missing = False
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        device = AudioUtilities.GetSpeakers()
        # Newer pycaw wraps IMMDevice in AudioDevice; fall back to ._dev for the raw COM object
        raw = getattr(device, '_dev', device)
        interface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol       = cast(interface, POINTER(IAudioEndpointVolume))

        if action == "volume_mute":
            # Toggle. Use the OS hotkey instead of pycaw SetMute — see
            # _press_mute_hotkey() for why. GetMute() is read-only and safe.
            pre_muted = bool(vol.GetMute())
            _press_mute_hotkey()
            time.sleep(0.08)
            post_muted = bool(vol.GetMute())
            # If the hotkey didn't take effect (no audio device, hotkey
            # intercepted by another process, etc.), surface that as an error
            # instead of returning a false "Muted" / "Unmuted" label.
            if post_muted == pre_muted:
                return _err("Mute toggle had no effect (OS hotkey not delivered)")
            return _ok("Muted" if post_muted else "Unmuted")

        if action == "volume_unmute":
            # Force-unmute. Hotkey is a toggle, so only press if currently muted.
            pre_muted = bool(vol.GetMute())
            if not pre_muted:
                return _ok("Unmuted")
            _press_mute_hotkey()
            time.sleep(0.08)
            if bool(vol.GetMute()):
                return _err("Unmute had no effect (OS hotkey not delivered)")
            return _ok("Unmuted")

        if level is not None:
            scalar = max(0.0, min(1.0, level / 100.0))
            vol.SetMasterVolumeLevelScalar(scalar, None)
            _osd_trigger(vol, scalar)
            return _ok(f"{level}%")

        current = int(vol.GetMasterVolumeLevelScalar() * 100)
        if action == "volume_up":
            new_level = min(100, current + 10)
        else:
            new_level = max(0, current - 10)
        vol.SetMasterVolumeLevelScalar(new_level / 100.0, None)
        _osd_trigger(vol, new_level / 100.0)
        return _ok(f"{new_level}%")

    except ImportError:
        pycaw_missing = True
    except Exception as exc:
        # Surface the real error — never silently swallow pycaw failures
        return _err(f"Volume control failed: {exc}")

    # Absolute level requires pycaw — pyautogui keys cannot target a specific %
    if level is not None:
        return _err("pycaw not installed — run: uv add pycaw  (required for absolute volume)")

    # Fallback: pyautogui media keys for step up/down/mute only (no pycaw)
    pag = _pag()
    if pag is None:
        return _err("pyautogui not installed — run: uv add pyautogui")
    try:
        key_map = {
            "volume_up":   "volumeup",
            "volume_down": "volumedown",
            "volume_mute": "volumemute",
            "volume_unmute": "volumemute",
        }
        key = key_map.get(action, "volumeup")
        presses = 5 if action in ("volume_up", "volume_down") else 1
        for _ in range(presses):
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
