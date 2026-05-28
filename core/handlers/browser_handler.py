"""Handler: browser_automation."""

from __future__ import annotations

from core.handlers.shared import _err, _set_page_cache


def _is_vague_selector(selector: str) -> bool:
    """A selector is 'vague' when it lacks CSS sigils that mark a precise locator.

    Used by the click_element auto-routing heuristic: if the brain sent only loose
    text (e.g. ``"Sign in button"``) instead of ``"#sign-in"`` / ``"button[type=…]"``,
    prefer the snapshot-driven picker over the legacy selector chain.
    """
    if not selector:
        return True
    return not any(ch in selector for ch in "#.[:>")


def _handle_browser_automation(action: str, params: dict) -> dict:
    from core.browser import browser

    if not browser.is_ready:
        browser.start()
        if not browser.is_ready:
            return _err(browser.start_error or "Browser failed to start.")

    url = params.get("url", "")

    if action == "navigate":
        if not url:
            return _err("No URL provided")
        return browser.navigate(url)

    if action == "new_tab":
        return browser.new_tab(url)

    if action == "switch_tab":
        # Accept several aliases so the brain doesn't have to remember the
        # exact key name. ``target`` is canonical; ``match`` / ``tab`` are
        # accepted because close_tab uses the same vocabulary.
        target = (
            (params.get("target") or params.get("match") or params.get("tab") or "")
        ).strip()
        return browser.switch_tab(target)

    if action == "click_element":
        goal     = (params.get("goal") or "").strip()
        selector = (params.get("selector") or "").strip()
        text     = (params.get("text") or "").strip()
        x        = params.get("x")
        y        = params.get("y")

        # Phase 2 — explicit goal from the brain wins.
        if goal:
            result = browser.find_and_act(goal, "click")
            if result.get("success"):
                return result
            # Hard miss after the internal fallback chain — give legacy a last shot
            # if any precise hints were also provided.
            if selector or text or (x is not None and y is not None):
                return browser.click_element(selector=selector, text=text, x=x, y=y)
            return result

        # Phase 3 — vague selector + text → try the snapshot picker first.
        if _is_vague_selector(selector) and text:
            result = browser.find_and_act(text, "click")
            if result.get("success"):
                return result
            return browser.click_element(selector=selector, text=text, x=x, y=y)

        return browser.click_element(selector=selector, text=text, x=x, y=y)

    if action == "fill_form":
        goal   = (params.get("goal") or "").strip()
        value  = params.get("value", "")
        fields = params.get("fields", {}) or {}

        # Phase 2 — goal + value path.
        if goal and value != "":
            result = browser.find_and_act(goal, "fill", str(value))
            if result.get("success"):
                return result
            if fields:
                return browser.fill_form(fields)
            return result

        return browser.fill_form(fields)

    if action in ("extract_text", "read_page"):
        selector = params.get("selector", "")
        result   = browser.extract_content(selector) if selector else browser.read_page()
        if result.get("success") and result.get("output"):
            _set_page_cache(result["output"])
        return result

    if action == "screenshot":
        selector = params.get("selector", "")
        path     = params.get("save_path") or None
        return (browser.screenshot_element(selector, path) if selector
                else browser.screenshot_page(path))

    if action == "close_tab":
        return browser.close_tab(
            title_contains=((params.get("title_contains") or params.get("title", "") or "")).strip(),
            url_contains=((params.get("url_contains") or params.get("url_match", "") or "")).strip(),
            match=((params.get("match") or params.get("tab") or params.get("target", "") or "")).strip(),
        )

    if action == "scroll":
        return browser.scroll(
            direction=(params.get("direction") or "down"),
            amount=params.get("amount", 3),
        )

    if action == "go_back":
        return browser.go_back()

    if action == "go_forward":
        return browser.go_forward()

    if action == "refresh":
        return browser.refresh()

    if action == "hard_refresh":
        return browser.hard_refresh()

    if action == "list_tabs":
        return browser.list_tabs()

    return _err(f"Browser action not implemented: {action}")
