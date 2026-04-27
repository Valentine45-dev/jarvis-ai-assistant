"""Handler: browser_automation."""

from __future__ import annotations

from core.handlers.shared import _err, _set_page_cache


def _handle_browser_automation(action: str, params: dict) -> dict:
    from core.browser import browser

    if not browser.is_ready:
        browser.start()
        if not browser.is_ready:
            return _err(browser._start_err or "Browser failed to start.")

    url = params.get("url", "")

    if action == "navigate":
        if not url:
            return _err("No URL provided")
        return browser.navigate(url)

    if action == "new_tab":
        return browser.new_tab(url)

    if action == "click_element":
        return browser.click_element(
            selector=params.get("selector", ""),
            text=params.get("text", ""),
            x=params.get("x"),
            y=params.get("y"),
        )

    if action == "fill_form":
        return browser.fill_form(params.get("fields", {}))

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

    return _err(f"Browser action not implemented: {action}")
