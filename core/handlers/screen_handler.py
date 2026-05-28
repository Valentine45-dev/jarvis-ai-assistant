"""Handler: read_screen (OCR)."""

from __future__ import annotations

from core.handlers.shared import _err, _ok, _set_page_cache, _tlog
from core import computer_control as cc


_OCR_LABELS = {
    "ocr_full":          "ocr full screen",
    "ocr_active_window": "ocr active window",
    "ocr_region":        "ocr region",
}


def _handle_read_screen(action: str, params: dict) -> dict:
    # ── find_element: OCR the screen, then filter by search_text ─────────────
    # Pre-fix this handler ran OCR but ignored ``search_text`` entirely, so
    # "find the Submit button" would dump the whole screen. Now it returns
    # the matching lines (or an explicit "not found" error).
    if action == "find_element":
        search_text = (params.get("search_text") or params.get("text") or "").strip()
        _tlog(f"❯ find {search_text!r} on screen")
        if not search_text:
            _tlog("✗ no search text provided")
            return _err("find_element requires a 'search_text' parameter.")
        ocr = cc.ocr_screen(region=None)
        if not ocr.get("success"):
            _tlog(f"✗ {ocr.get('error') or 'ocr failed'}")
            return ocr
        ocr_text = ocr.get("output") or ""
        if not ocr_text:
            _tlog("✗ ocr returned empty")
            return _err(f"OCR returned no text — {search_text!r} not found on screen.")
        # Case-insensitive substring search, line by line.
        needle = search_text.lower()
        hits = [ln.strip() for ln in ocr_text.splitlines() if needle in ln.lower()]
        if not hits:
            _tlog(f"✗ {search_text!r} not on screen")
            return _err(f"{search_text!r} not found on screen.")
        _set_page_cache(ocr_text)
        n = len(hits)
        snippet = "\n".join(hits[:5])
        if n > 5:
            snippet += f"\n[…and {n - 5} more match{'es' if n - 5 != 1 else ''}]"
        _tlog(f"✓ {n} match{'es' if n != 1 else ''}")
        return _ok(f"Found {n} match{'es' if n != 1 else ''} for {search_text!r}:\n{snippet}")

    # ── OCR full / active-window / region — unchanged behaviour ──────────────
    _tlog(f"❯ {_OCR_LABELS.get(action, 'ocr')}")
    region = params.get("region") if action == "ocr_region" else None
    result = cc.ocr_screen(region=region)
    if result.get("success") and result.get("output"):
        _set_page_cache(result["output"])
        _tlog(f"✓ extracted {len(result['output'])} chars")
    elif result.get("success"):
        _tlog("✓ extracted 0 chars")
    else:
        _tlog(f"✗ {result.get('error') or 'ocr failed'}")
    return result
