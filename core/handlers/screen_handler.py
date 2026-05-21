"""Handler: read_screen (OCR)."""

from __future__ import annotations

from core.handlers.shared import _set_page_cache, _tlog
from core import computer_control as cc


_OCR_LABELS = {
    "ocr_full":          "ocr full screen",
    "ocr_active_window": "ocr active window",
    "ocr_region":        "ocr region",
}


def _handle_read_screen(action: str, params: dict) -> dict:
    if action == "find_element":
        search_text = (params.get("search_text") or params.get("text") or "").strip()
        _tlog(f"❯ find {search_text!r} on screen")
    else:
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
