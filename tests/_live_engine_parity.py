"""Live parity check: drive EVERY browser capability on Edge and Firefox the
same way it works on Chrome. Opens real windows. Run:  uv run python tests/_live_engine_parity.py
Throwaway manual script (underscore prefix → not collected by pytest)."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.browser import browser

RICH_HTML = """
<html><body style='margin:0;font-family:sans-serif'>
<h1 id='title'>JARVIS Engine Test</h1>
<p id='lead'>Reusing every Chrome capability.</p>
<form>
  <input id='q' name='q' placeholder='Search here' style='width:320px;height:30px'>
  <button id='go' type='button'>Go</button>
</form>
<div id='sec'>
  <h2>Section heading</h2>
  <button>Alpha</button><br><button>Beta</button><br><button>Gamma</button>
</div>
<div style='height:1800px'>spacer</div>
<div id='bottom'>BOTTOM MARKER</div>
</body></html>
"""

TMP = tempfile.gettempdir()


def run_suite(engine: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            ok, detail = fn()
            out.append((name, bool(ok), str(detail)[:80]))
        except Exception as exc:  # noqa: BLE001 — report, don't abort the suite
            out.append((name, False, f"EXC {type(exc).__name__}: {exc}"[:80]))

    # ── engine up ─────────────────────────────────────────────────────────────
    r = browser.ensure_engine(engine)
    out.append(("ensure_engine", r.get("success", False), r.get("output") or r.get("error", "")))
    if not browser.is_ready:
        return out

    page = browser._page  # active engine's page (property)

    # Load a rich interaction page (set_content avoids navigate's scheme munging).
    check("set_content", lambda: (page.set_content(RICH_HTML) or True,
                                  "rich test page loaded"))

    # ── read / extract ────────────────────────────────────────────────────────
    check("read_page", lambda: (
        "JARVIS Engine Test" in browser.read_page().get("output", ""), "title text present"))
    check("extract_content(#title)", lambda: (
        browser.extract_content("#title").get("output", "").strip() == "JARVIS Engine Test",
        browser.extract_content("#title").get("output", "").strip()))

    # ── click ─────────────────────────────────────────────────────────────────
    check("click_element(selector)", lambda: (
        browser.click_element(selector="#go").get("success"), "clicked #go"))
    check("click_element(text)", lambda: (
        browser.click_element(text="Alpha").get("success"), "clicked Alpha"))

    # ── fill (selector dict + Haiku goal) ──────────────────────────────────────
    def _fill_fields():
        browser.fill_form({"#q": "hello"})
        return page.evaluate("document.querySelector('#q').value") == "hello", "value=hello"
    check("fill_form(fields)", _fill_fields)

    def _fill_goal():
        page.evaluate("document.querySelector('#q').value=''")
        browser.find_and_act("search box", "fill", "world")
        return page.evaluate("document.querySelector('#q').value") == "world", "value=world (Haiku)"
    check("fill_form(goal/Haiku)", _fill_goal)

    # ── click via Haiku goal ───────────────────────────────────────────────────
    check("click(goal/Haiku)", lambda: (
        browser.find_and_act("the Go button", "click").get("success"), "Haiku click"))

    # ── screenshots: page full / viewport / element / region(union) ────────────
    def _shot(call, fname):
        p = os.path.join(TMP, f"{engine}_{fname}")
        r = call(p)
        return r.get("success") and os.path.exists(p) and os.path.getsize(p) > 0, fname
    check("screenshot_page(full)", lambda: _shot(
        lambda p: browser.screenshot_page(p, full_page=True), "full.png"))
    check("screenshot_page(viewport)", lambda: _shot(
        lambda p: browser.screenshot_page(p, full_page=False), "viewport.png"))
    check("screenshot_element(#sec)", lambda: _shot(
        lambda p: browser.screenshot_element("#sec", p), "element.png"))
    check("screenshot region(goal/union)", lambda: _shot(
        lambda p: browser.find_and_act(
            "the Section heading and the Alpha Beta Gamma buttons", "screenshot", path=p),
        "region.png"))

    # ── scroll ─────────────────────────────────────────────────────────────────
    check("scroll(down)", lambda: (browser.scroll("down", 5).get("success"), "down 5"))
    check("scroll(up)", lambda: (browser.scroll("up", 5).get("success"), "up 5"))

    # ── tabs: new / list / switch / close ──────────────────────────────────────
    check("new_tab", lambda: (browser.new_tab("https://example.net").get("success"), "example.net"))
    check("list_tabs", lambda: (
        "2 tab" in browser.list_tabs().get("output", "").lower()
        or browser.list_tabs().get("success"), browser.list_tabs().get("output", "")[:50]))
    check("switch_tab", lambda: (browser.switch_tab("example").get("success"), "→ example.net"))
    check("close_tab(match)", lambda: (
        browser.close_tab(match="example").get("success"), "closed example tab"))

    # ── navigation + history on real stable sites ──────────────────────────────
    check("navigate(example.com)", lambda: (
        browser.navigate("https://example.com").get("success"), "example.com"))
    check("navigate(example.net)", lambda: (
        browser.navigate("https://example.net").get("success"), "example.net"))
    check("go_back", lambda: (browser.go_back().get("success"), "back→example.com"))
    check("go_forward", lambda: (browser.go_forward().get("success"), "fwd→example.net"))
    check("refresh", lambda: (browser.refresh().get("success"), "reloaded"))
    check("hard_refresh", lambda: (browser.hard_refresh().get("success"), "cache-bypass reload"))

    return out


def _safe(s: str) -> str:
    """Strip non-cp1252 chars so Windows console prints don't crash the run."""
    return s.encode("ascii", "replace").decode("ascii")


def main() -> None:
    engines = ["edge", "firefox"]
    all_results: dict[str, list[tuple[str, bool, str]]] = {}
    for eng in engines:
        print(f"\n{'='*70}\n  ENGINE: {eng.upper()}\n{'='*70}")
        res = run_suite(eng)
        all_results[eng] = res
        for name, ok, detail in res:
            print(_safe(f"  [{'PASS' if ok else 'FAIL'}] {name:<28} {detail}"))

    print(f"\n{'='*70}\n  SUMMARY\n{'='*70}")
    for eng, res in all_results.items():
        passed = sum(1 for _, ok, _ in res if ok)
        total = len(res)
        fails = [n for n, ok, _ in res if not ok]
        print(f"  {eng:<8} {passed}/{total} passed" + (f"  | FAILED: {', '.join(fails)}" if fails else "  | all green"))

    try:
        browser.stop()
        print("\n  Closed all engines.")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  stop() error: {exc}")


if __name__ == "__main__":
    main()
