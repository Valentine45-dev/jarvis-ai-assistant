"""Handler: vision_analysis — capture an image, send it to Claude vision.

Mirror of core/handlers/screen_handler.py shape: validate params, drive
the capture, send to the analyser, cache the result for follow-ups,
emit one terminal line per stage. No UI, no signals, no Qt — everything
flows back to the caller as ``_ok`` / ``_err`` dicts.

Source values:
  - ``screenshot`` (default) — primary monitor
  - ``region``                — sub-rect of the primary monitor
  - ``webcam``                — single frame from a cv2.VideoCapture
  - ``file``                  — image on disk loaded via Pillow
  - ``browser``               — viewport of the active Playwright page
"""

from __future__ import annotations

from config.settings import config
from core import vision
from core.handlers.shared import _err, _ok, _set_page_cache, _tlog


def _handle_vision_analysis(action: str, params: dict) -> dict:
    source   = params.get("source", "screenshot")
    path     = (params.get("path") or "").strip()
    question = (params.get("question") or "").strip()
    region   = params.get("region")
    device   = int(params.get("device") or 0)

    _tlog(f"❯ vision {action} via {source}")

    # ── Capture ──────────────────────────────────────────────────────────────
    try:
        if source == "file":
            if not path:
                _tlog("✗ source=file requires path")
                return _err("source=file requires path")
            image_bytes = vision.load_image_file(path)

        elif source == "region":
            if not region:
                _tlog("✗ source=region requires region {x, y, width, height}")
                return _err("source=region requires region {x, y, width, height}")
            image_bytes = vision.capture_region(
                int(region["x"]),
                int(region["y"]),
                int(region["width"]),
                int(region["height"]),
            )

        elif source == "webcam":
            image_bytes = vision.capture_webcam(device)

        elif source == "browser":
            image_bytes = vision.capture_browser_page()

        else:  # "screenshot" + "screenshot_and_describe" + any unknown source
            image_bytes = vision.capture_screenshot()

    except FileNotFoundError:
        _tlog(f"✗ file not found: {path}")
        return _err(f"Image file not found: {path}")
    except (RuntimeError, ValueError) as exc:
        _tlog(f"✗ capture failed: {exc}")
        return _err(str(exc))
    except Exception as exc:
        _tlog(f"✗ capture error: {exc}")
        return _err(f"Capture failed: {exc}")

    _tlog(f"↳ captured {len(image_bytes):,} bytes")

    # ── Analyze ──────────────────────────────────────────────────────────────
    try:
        result = vision.analyze_image(image_bytes, question, action)
    except Exception as exc:
        _tlog(f"✗ analysis failed: {exc}")
        return _err(f"Vision analysis failed: {exc}")

    # Cache the analysis so a follow-up like "what did you see?" can
    # reuse it via the existing page-cache path used by browser/OCR.
    _set_page_cache(result)

    # Optional: stream the raw analysis to the terminal panel during
    # rollout. Off by default — flip ``config.vision_show_analysis = True``
    # while debugging or demoing.
    if getattr(config, "vision_show_analysis", False):
        for line in result.splitlines():
            if line.strip():
                _tlog(f"↳ {line.strip()}")

    _tlog(f"✓ analyzed — {len(result)} chars")
    return _ok(result)
