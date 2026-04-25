"""
Interactive test runner for core/executor.py intent handlers.
Run with: uv run python tests/test_executor.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.executor import dispatch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _report(name: str, result: dict) -> bool:
    ok = result.get("success", False)
    status = "PASS" if ok else "FAIL"
    out = result.get("output", "")
    err = result.get("error", "")
    print(f"\n  [{status}] {name}")
    if out:
        print(f"         output : {out[:160]}")
    if err:
        print(f"         error  : {err}")
    return ok


def _pause():
    input("\n  Press ENTER to run this test...")


def _call(intent: str, action: str, parameters: dict = None) -> dict:
    return dispatch({
        "intent": intent,
        "action": action,
        "parameters": parameters or {},
        "requires_confirmation": False,
    })


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_open_app():
    print("\n─── OPEN APP ────────────────────────────────────────────────")
    print("  Opens Notepad via open_app_generic.")
    _pause()

    r = _call("open_app", "open_app_generic", {"app_name": "notepad"})
    _report("open_app → notepad", r)
    print("  ↑ Check: did Notepad open?")


def test_close_app():
    print("\n─── CLOSE APP ───────────────────────────────────────────────")
    print("  Closes Notepad. Make sure it is still open from the previous test.")
    _pause()

    r = _call("close_app", "close_app", {"app_name": "notepad"})
    _report("close_app → notepad", r)
    print("  ↑ Check: did Notepad close?")


def test_search_google():
    print("\n─── SEARCH WEB (Google) ─────────────────────────────────────")
    print("  Opens Google search for 'JARVIS AI assistant'.")
    _pause()

    r = _call("search_web", "google_search", {"query": "JARVIS AI assistant", "platform": "google"})
    _report("search_web → google: 'JARVIS AI assistant'", r)


def test_search_youtube():
    print("\n─── SEARCH WEB (YouTube) ────────────────────────────────────")
    print("  Opens YouTube search for 'Iron Man JARVIS scene'.")
    _pause()

    r = _call("search_web", "youtube_search", {"query": "Iron Man JARVIS scene", "platform": "youtube"})
    _report("search_web → youtube: 'Iron Man JARVIS scene'", r)


def test_file_create():
    print("\n─── FILE CREATE ─────────────────────────────────────────────")
    print("  Creates ~/Desktop/jarvis_test.txt with content 'JARVIS was here'.")
    _pause()

    r = _call("file_operation", "create_file", {
        "path": "~/Desktop/jarvis_test.txt",
        "content": "JARVIS was here",
    })
    _report("file_operation → create_file", r)


def test_file_read():
    print("\n─── FILE READ ───────────────────────────────────────────────")
    print("  Reads ~/Desktop/jarvis_test.txt back.")
    _pause()

    r = _call("file_operation", "read_file", {"path": "~/Desktop/jarvis_test.txt"})
    ok = r.get("success") and "JARVIS was here" in r.get("output", "")
    r["success"] = ok
    _report("file_operation → read_file (content verified)", r)


def test_file_list():
    print("\n─── FILE LIST ───────────────────────────────────────────────")
    print("  Lists ~/Desktop directory.")
    _pause()

    r = _call("file_operation", "list_directory", {"path": "~/Desktop"})
    _report("file_operation → list_directory: ~/Desktop", r)


def test_file_delete():
    print("\n─── FILE DELETE ─────────────────────────────────────────────")
    print("  Deletes ~/Desktop/jarvis_test.txt.")
    print("  NOTE: requires_confirmation is bypassed in this test harness.")
    _pause()

    r = _call("file_operation", "delete_file", {"path": "~/Desktop/jarvis_test.txt"})
    _report("file_operation → delete_file", r)


def test_mouse_right_click():
    print("\n─── MOUSE RIGHT CLICK ───────────────────────────────────────")
    print("  Right-clicks at (500, 500). A context menu should appear.")
    _pause()

    r = _call("control_mouse", "right_click", {"x": 500, "y": 500})
    _report("control_mouse → right_click (500, 500)", r)
    print("  ↑ Check: did a context menu appear?")


def test_mouse_scroll():
    print("\n─── MOUSE SCROLL ────────────────────────────────────────────")
    print("  Scrolls down 3 clicks at current mouse position.")
    _pause()

    r = _call("control_mouse", "scroll", {"direction": "down", "amount": 3})
    _report("control_mouse → scroll down 3", r)
    print("  ↑ Check: did the page/window scroll down?")


def test_mouse_drag():
    print("\n─── MOUSE DRAG ──────────────────────────────────────────────")
    print("  Drags from (300, 300) to (500, 500). Watch your cursor.")
    _pause()

    r = _call("control_mouse", "drag", {"from_x": 300, "from_y": 300, "to_x": 500, "to_y": 500})
    _report("control_mouse → drag (300,300) → (500,500)", r)
    print("  ↑ Check: did the cursor drag across the screen?")


def test_tell_time():
    print("\n─── JARVIS META: TIME ───────────────────────────────────────")
    print("  Returns the current time.")
    _pause()

    r = _call("jarvis_meta", "tell_time")
    _report("jarvis_meta → tell_time", r)


def test_tell_date():
    print("\n─── JARVIS META: DATE ───────────────────────────────────────")
    print("  Returns the current date.")
    _pause()

    r = _call("jarvis_meta", "tell_date")
    _report("jarvis_meta → tell_date", r)


def test_status_report():
    print("\n─── JARVIS META: STATUS ─────────────────────────────────────")
    print("  Returns CPU and RAM usage.")
    _pause()

    r = _call("jarvis_meta", "status_report")
    _report("jarvis_meta → status_report", r)


def test_reminder():
    print("\n─── REMINDER TASK ───────────────────────────────────────────")
    print("  Sets a 10-second reminder: 'Test reminder'.")
    print("  The HUD status signal fires after 10 s (visible in debug logs if running main.py).")
    _pause()

    r = _call("reminder_task", "set_reminder", {
        "message": "Test reminder",
        "delay_seconds": 10,
        "repeat": False,
    })
    _report("reminder_task → set_reminder (10s)", r)
    if r.get("success"):
        print("  Waiting 11 seconds for reminder to fire...")
        time.sleep(11)
        print("  ↑ If JARVIS is running, the HUD status bar should have shown REMINDER: Test reminder")


# ── Menu ──────────────────────────────────────────────────────────────────────

TESTS = {
    "1":  ("open_app        — launch Notepad",                  test_open_app),
    "2":  ("close_app       — close Notepad",                   test_close_app),
    "3":  ("search_web      — Google: JARVIS AI assistant",     test_search_google),
    "4":  ("search_web      — YouTube: Iron Man JARVIS scene",  test_search_youtube),
    "5":  ("file create     — ~/Desktop/jarvis_test.txt",       test_file_create),
    "6":  ("file read       — verify content",                  test_file_read),
    "7":  ("file list       — ~/Desktop",                       test_file_list),
    "8":  ("file delete     — ~/Desktop/jarvis_test.txt",       test_file_delete),
    "9":  ("mouse right_click — (500, 500)",                    test_mouse_right_click),
    "10": ("mouse scroll    — down 3",                          test_mouse_scroll),
    "11": ("mouse drag      — (300,300) → (500,500)",           test_mouse_drag),
    "12": ("jarvis_meta     — tell_time",                       test_tell_time),
    "13": ("jarvis_meta     — tell_date",                       test_tell_date),
    "14": ("jarvis_meta     — status_report",                   test_status_report),
    "15": ("reminder_task   — 10s 'Test reminder'",             test_reminder),
    "a":  ("ALL             — run every test in order",         None),
}


def main():
    print("=" * 60)
    print("  JARVIS — executor.py test suite")
    print("=" * 60)

    while True:
        print("\n  Pick a test to run:\n")
        for key, (label, _) in TESTS.items():
            print(f"    [{key:>2}] {label}")
        print("    [ q] Quit\n")

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
