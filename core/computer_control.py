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


def _press_volume_step_hotkey(direction: str, presses: int = 5) -> bool:
    """Send VK_VOLUME_UP / VK_VOLUME_DOWN N times. Native OSD shows automatically.

    Same rationale as _press_mute_hotkey — avoids the pycaw SetMasterVolumeLevelScalar
    path on the step branch so we don't leak comtypes COM proxies that later
    crash with `ValueError: COM method call without VTable` when Python GC
    reaps them. Returns True if any press landed; False if no backend worked.
    """
    pag = _pag()
    key = "volumeup" if direction == "up" else "volumedown"
    if pag is not None:
        try:
            for _ in range(presses):
                pag.press(key)
            return True
        except Exception:
            pass
    if _OS == "windows":
        try:
            import ctypes
            vk = 0xAF if direction == "up" else 0xAE  # VK_VOLUME_UP / VK_VOLUME_DOWN
            KEYEVENTF_KEYUP = 0x02
            for _ in range(presses):
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            return False
    return False


def set_volume(action: str, level: int | None = None) -> dict:
    # ── Mute path — pure OS hotkey, no pycaw, no COM proxies. ─────────────────
    # Kept above the pycaw block so a mute toggle never instantiates a
    # comtypes COM proxy. pycaw proxies accumulate as stale references that
    # later crash with `ValueError: COM method call without VTable` when
    # Python GC reaps them on a thread without a live COM apartment.
    # Mute state is tracked at the handler layer via _app_audio_muted.
    if action in ("volume_mute", "volume_unmute"):
        _press_mute_hotkey()
        time.sleep(0.08)
        return _ok("toggled")

    # ── Step path (volume_up / volume_down without explicit level) ────────────
    # Pure OS hotkey, native Windows OSD shows automatically. No pycaw, so no
    # COM proxies to leak. Each press is ~2% on Windows; 5 presses ≈ 10% per
    # command which matches the prior pycaw step size.
    if action in ("volume_up", "volume_down") and level is None:
        direction = "up" if action == "volume_up" else "down"
        if _press_volume_step_hotkey(direction, presses=5):
            return _ok("Louder" if direction == "up" else "Softer")
        return _err("Volume hotkey unavailable — install pyautogui or check OS support")

    # ── Absolute level path — needs pycaw (hotkeys can't target a specific %) ─
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        device = AudioUtilities.GetSpeakers()
        # Newer pycaw wraps IMMDevice in AudioDevice; fall back to ._dev for the raw COM object
        raw = getattr(device, '_dev', device)
        interface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol       = cast(interface, POINTER(IAudioEndpointVolume))

        scalar = max(0.0, min(1.0, (level or 0) / 100.0))
        vol.SetMasterVolumeLevelScalar(scalar, None)
        _osd_trigger(vol, scalar)
        return _ok(f"{level}%")

    except ImportError:
        return _err("pycaw not installed — run: uv add pycaw  (required for absolute volume)")
    except Exception as exc:
        return _err(f"Volume control failed: {exc}")


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
