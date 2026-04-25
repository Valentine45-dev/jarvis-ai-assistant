"""
Interactive test runner for core/browser.py
Run with: uv run python tests/test_browser.py
Tests browser.* directly — no Claude API or executor needed.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.browser import browser


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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_start():
    print("\n─── BROWSER START ───────────────────────────────────────────")
    print("  Calls browser.start() — Chrome should open with about:blank.")
    _pause()

    browser.start()
    if browser._ready:
        result = {"success": True, "output": "Browser session started — Chrome is open"}
    else:
        result = {"success": False, "output": "", "error": browser._start_err}
    _report("browser.start()", result)
    print("  ↑ Check: did a Chrome window open with about:blank?")


def test_navigate_github():
    print("\n─── NAVIGATE: github.com ────────────────────────────────────")
    print("  Navigates to https://github.com in the Playwright-controlled Chrome tab.")
    _pause()

    r = browser.navigate("https://github.com")
    _report("browser.navigate('https://github.com')", r)
    print("  ↑ Check: did the Chrome tab navigate to GitHub?")


def test_navigate_google():
    print("\n─── NAVIGATE: google.com ────────────────────────────────────")
    print("  Navigates to https://google.com — same tab, same session.")
    _pause()

    r = browser.navigate("https://google.com")
    _report("browser.navigate('https://google.com')", r)
    print("  ↑ Check: did the Chrome tab navigate to Google?")


def test_navigate_youtube():
    print("\n─── NAVIGATE: youtube.com ───────────────────────────────────")
    print("  Navigates to https://youtube.com.")
    _pause()

    r = browser.navigate("https://youtube.com")
    _report("browser.navigate('https://youtube.com')", r)


def test_navigate_no_scheme():
    print("\n─── NAVIGATE: no https:// prefix ────────────────────────────")
    print("  Navigates to 'github.com' (no scheme) — should auto-prefix https://.")
    _pause()

    r = browser.navigate("github.com")
    _report("browser.navigate('github.com') — auto https://", r)


def test_navigate_bad_url():
    print("\n─── NAVIGATE: bad URL (error handling) ──────────────────────")
    print("  Navigates to a non-existent domain — should return FAIL, not crash.")
    _pause()

    r = browser.navigate("https://this-domain-does-not-exist-jarvis-test.xyz")
    _report("browser.navigate(bad URL) — expect FAIL gracefully", r)


def test_read_page():
    print("\n─── READ PAGE ───────────────────────────────────────────────")
    print("  Navigates to github.com then reads visible page text.")
    _pause()

    browser.navigate("https://github.com")
    r = browser.read_page()
    _report("browser.read_page() on github.com", r)
    print("  ↑ Check: output should contain readable GitHub homepage text.")


def test_extract_content():
    print("\n─── EXTRACT CONTENT ─────────────────────────────────────────")
    print("  Extracts text from the <h1> element on the current page.")
    _pause()

    r = browser.extract_content("h1")
    _report("browser.extract_content('h1')", r)


def test_click_text():
    print("\n─── CLICK BY TEXT ───────────────────────────────────────────")
    print("  Navigates to github.com and clicks 'Sign in' by visible text.")
    _pause()

    browser.navigate("https://github.com")
    r = browser.click_element(text="Sign in")
    _report("browser.click_element(text='Sign in')", r)
    print("  ↑ Check: should have navigated to github.com/login")


def test_fill_form():
    print("\n─── FILL FORM ───────────────────────────────────────────────")
    print("  Fills GitHub login form — username field only (no submit).")
    _pause()

    browser.navigate("https://github.com/login")
    r = browser.fill_form({"input[name='login']": "jarvis_test_user"})
    _report("browser.fill_form({'input[name=login]': 'jarvis_test_user'})", r)
    print("  ↑ Check: 'jarvis_test_user' typed into the Username field.")


def test_click_selector():
    print("\n─── CLICK BY SELECTOR ───────────────────────────────────────")
    print("  Clicks the password field on github.com/login by CSS selector.")
    _pause()

    browser.navigate("https://github.com/login")
    r = browser.click_element(selector="input[name='password']")
    _report("browser.click_element(selector='input[name=password]')", r)
    print("  ↑ Check: password field should be focused.")


def test_screenshot_page():
    print("\n─── SCREENSHOT PAGE ─────────────────────────────────────────")
    print("  Takes a full-page screenshot and saves to Desktop.")
    _pause()

    browser.navigate("https://github.com")
    r = browser.screenshot_page()
    _report("browser.screenshot_page()", r)
    if r.get("success"):
        print("  ↑ Check Desktop for: jarvis_browser_screenshot.png")


def test_new_tab():
    print("\n─── NEW TAB ─────────────────────────────────────────────────")
    print("  Opens a new tab and navigates to google.com.")
    _pause()

    r = browser.new_tab("https://google.com")
    _report("browser.new_tab('https://google.com')", r)
    print("  ↑ Check: Chrome should have a second tab open on Google.")


def test_close_tab():
    print("\n─── CLOSE TAB ───────────────────────────────────────────────")
    print("  Closes the active tab and switches to the previous one.")
    _pause()

    r = browser.close_tab()
    _report("browser.close_tab()", r)
    print("  ↑ Check: second tab closed, first tab is now active.")


def test_stop():
    print("\n─── BROWSER STOP ────────────────────────────────────────────")
    print("  Calls browser.stop() — Chrome should close.")
    _pause()

    browser.stop()
    result = {"success": not browser._ready, "output": "Browser session closed", "error": ""}
    _report("browser.stop()", result)
    print("  ↑ Check: did the Chrome window close?")


# ── Menu ──────────────────────────────────────────────────────────────────────

TESTS = {
    "1":  ("start()                       — launch Chrome",               test_start),
    "2":  ("navigate('github.com')        — GitHub",                      test_navigate_github),
    "3":  ("navigate('google.com')        — Google",                      test_navigate_google),
    "4":  ("navigate('youtube.com')       — YouTube",                     test_navigate_youtube),
    "5":  ("navigate(no scheme)           — auto https:// prefix",        test_navigate_no_scheme),
    "6":  ("navigate(bad URL)             — graceful error, no crash",    test_navigate_bad_url),
    "7":  ("read_page()                   — extract visible text",        test_read_page),
    "8":  ("extract_content('h1')         — get heading text",            test_extract_content),
    "9":  ("click_element(text=Sign in)   — click by visible text",       test_click_text),
    "10": ("fill_form(login field)        — fill GitHub username",        test_fill_form),
    "11": ("click_element(selector=...)   — click by CSS selector",       test_click_selector),
    "12": ("screenshot_page()            — full-page screenshot",         test_screenshot_page),
    "13": ("new_tab('google.com')         — open second tab",             test_new_tab),
    "14": ("close_tab()                   — close active tab",            test_close_tab),
    "15": ("stop()                        — close Chrome",                test_stop),
    "a":  ("ALL                           — full end-to-end session",     None),
}


def main():
    print("=" * 60)
    print("  JARVIS — browser.py test suite")
    print("=" * 60)
    print("\n  NOTE: Tests 2–14 require browser.start() (test 1) first.")
    print("  Run ALL [a] for a full end-to-end session test.")

    while True:
        print("\n  Pick a test to run:\n")
        for key, (label, _) in TESTS.items():
            print(f"    [{key}] {label}")
        print("    [q] Quit\n")

        choice = input("  > ").strip().lower()

        if choice == "q":
            browser.stop()
            print("\n  Done. Chrome closed.\n")
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
