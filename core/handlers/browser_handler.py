"""Handler: browser_automation."""

from __future__ import annotations

from core.handlers.shared import _err, _set_page_cache


def _as_bool(v) -> bool:
    """Coerce a brain-supplied value to bool (JSON true/false arrive as Python
    bool; strings like 'false'/'no'/'0' are handled too)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "no", "0", "off", "")
    return bool(v)


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

    # close_engine / close_all_engines must run BEFORE the auto-start guard —
    # closing a browser should never first launch one.
    if action == "close_engine":
        engine = (params.get("browser") or params.get("engine")
                  or params.get("target") or "").strip()
        return browser.close_engine(engine)

    # close_all_engines: the executor enumerates the live engine registry at run
    # time, so the brain never has to name/count engines (immune to a wrong guess).
    if action == "close_all_engines":
        return browser.close_all_engines()

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
        goal     = (params.get("goal") or "").strip()
        path     = params.get("save_path") or None
        # full_page defaults True (whole scrollable page); the brain sets it False
        # for "just the visible part / current view". Accept a couple of aliases.
        fp_raw = params.get("full_page")
        if fp_raw is None:
            fp_raw = params.get("viewport_only")
            full_page = True if fp_raw is None else not _as_bool(fp_raw)
        else:
            full_page = _as_bool(fp_raw)
        # Priority: explicit CSS selector → element; natural-language goal →
        # capture-that-section via the snapshot picker; else → whole/visible page.
        if selector:
            return browser.screenshot_element(selector, path)
        if goal:
            return browser.find_and_act(goal, "screenshot", path=path)
        return browser.screenshot_page(path, full_page=full_page)

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
