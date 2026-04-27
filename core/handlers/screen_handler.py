"""Handler: read_screen (OCR)."""

from __future__ import annotations

from core.handlers.shared import _set_page_cache
from core import computer_control as cc


def _handle_read_screen(action: str, params: dict) -> dict:
    region = params.get("region") if action == "ocr_region" else None
    result = cc.ocr_screen(region=region)
    if result.get("success") and result.get("output"):
        _set_page_cache(result["output"])
    return result
