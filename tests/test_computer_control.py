"""
Interactive test runner for core/computer_control.py
Run with: uv run python tests/test_computer_control.py
"""

import sys
import os

# Allow running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.computer_control import (
    set_clipboard, get_clipboard,
    press_key, type_text,
    screenshot, ocr_screen,
    move, click,
    set_volume,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _report(name: str, result: dict) -> bool:
    ok = result.get("success", False)
    status = "PASS" if ok else "FAIL"
    out = result.get("output", "")
    err = result.get("error", "")
    print(f"\n  [{status}] {name}")
    if out:
        print(f"         output : {out[:120]}")
    if err:
        print(f"         error  : {err}")
    return ok


def _pause():
    input("\n  Press ENTER to run this test...")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_clipboard():
    print("\n─── CLIPBOARD ───────────────────────────────────────────────")
    print("  Sets clipboard to 'JARVIS test', then reads it back.")
    _pause()

    r1 = set_clipboard("JARVIS test")
    _report("set_clipboard('JARVIS test')", r1)

    r2 = get_clipboard()
    ok = r2.get("success") and r2.get("output", "").strip() == "JARVIS test"
    r2["success"] = ok   # override so _report shows correct status
    _report("get_clipboard() == 'JARVIS test'", r2)


def test_keyboard():
    print("\n─── KEYBOARD ────────────────────────────────────────────────")
    print("  Sends Ctrl+Shift+Esc — Task Manager should open.")
    _pause()

    r = press_key("ctrl+shift+esc")
    _report("press_key('ctrl+shift+esc')", r)
    print("  ↑ Check: did Task Manager open?")


def test_screenshot():
    print("\n─── SCREENSHOT ──────────────────────────────────────────────")
    print("  Takes a screenshot and saves it to your Desktop.")
    _pause()

    r = screenshot()
    _report("screenshot()", r)
    if r.get("success"):
        print(f"  ↑ Check your Desktop for: jarvis_screenshot.png")


def test_ocr():
    print("\n─── OCR / READ SCREEN ───────────────────────────────────────")
    print("  Reads text from the full screen using Tesseract.")
    _pause()

    r = ocr_screen()
    if r.get("success"):
        preview = r.get("output", "")[:200].replace("\n", " ").strip()
        r["output"] = preview
    _report("ocr_screen()", r)


def test_mouse():
    print("\n─── MOUSE ───────────────────────────────────────────────────")
    print("  Moves the mouse to (500, 500) — watch your cursor.")
    _pause()

    r = move(500, 500)
    _report("move(500, 500)", r)
    print("  ↑ Check: did your cursor move?")


def test_volume():
    print("\n─── VOLUME ──────────────────────────────────────────────────")
    print("  Sends volume_up then volume_down — net change is zero.")
    _pause()

    r1 = set_volume("volume_up")
    _report("set_volume('volume_up')", r1)

    r2 = set_volume("volume_down")
    _report("set_volume('volume_down')", r2)
    print("  ↑ Check: did you hear/see the volume OSD briefly?")


# ── Menu ──────────────────────────────────────────────────────────────────────

TESTS = {
    "1": ("Clipboard  — set + get",           test_clipboard),
    "2": ("Keyboard   — Ctrl+Shift+Esc",       test_keyboard),
    "3": ("Screenshot — save to Desktop",      test_screenshot),
    "4": ("OCR        — read full screen",     test_ocr),
    "5": ("Mouse      — move to (500, 500)",   test_mouse),
    "6": ("Volume     — up then down",         test_volume),
    "a": ("ALL        — run every test",       None),
}


def main():
    print("=" * 60)
    print("  JARVIS — computer_control.py test suite")
    print("=" * 60)

    while True:
        print("\n  Pick a test to run:\n")
        for key, (label, _) in TESTS.items():
            print(f"    [{key}] {label}")
        print("    [q] Quit\n")

        choice = input("  > ").strip().lower()

        if choice == "q":
            print("\n  Done.\n")
            break
        elif choice == "a":
            for key, (_, fn) in TESTS.items():
                if fn:
                    fn()
        elif choice in TESTS:
            _, fn = TESTS[choice]
            if fn:
                fn()
        else:
            print("  Unknown choice — try again.")


if __name__ == "__main__":
    main()
