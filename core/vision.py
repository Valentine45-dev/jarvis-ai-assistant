"""Vision capture + analysis primitives.

Single module for everything the ``vision_analysis`` intent needs:

  - five capture functions returning PNG bytes (screenshot, region,
    webcam, file load, browser page),
  - one ``analyze_image`` that ships the bytes to Claude vision and
    returns the response text,
  - a SHA-256-keyed in-process cache (max 20 entries, FIFO eviction)
    so identical screenshots don't re-pay for analysis when the user
    asks a follow-up like "what did you see?".

Pure functions only — no UI, no Qt signals. The dispatch layer is
``core/handlers/vision_handler.py``; the caller is responsible for
catching exceptions and shaping them into ``_ok``/``_err`` dicts.
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from config.settings import config
from core.log import debug as _dbg

# ── Cache ────────────────────────────────────────────────────────────────────
# SHA-256(image_bytes) -> analysis text. OrderedDict gives us FIFO behaviour
# via ``popitem(last=False)`` once the dict outgrows the cap. Module-global
# (not thread-locked) because every caller goes through
# ``vision_handler._handle_vision_analysis`` which is dispatched on the Qt
# main thread by core/executor.py — no concurrent writers in practice.

_vision_cache: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX_ENTRIES = 20


def clear_vision_cache() -> None:
    """Wipe the analysis cache. Used by tests; safe to call any time."""
    _vision_cache.clear()


def _cache_put(key: str, value: str) -> None:
    """Insert and enforce the cap. FIFO eviction (oldest key first)."""
    if key in _vision_cache:
        # Move to end so a re-cache doesn't get evicted before fresher keys.
        _vision_cache.move_to_end(key)
        _vision_cache[key] = value
        return
    _vision_cache[key] = value
    while len(_vision_cache) > _CACHE_MAX_ENTRIES:
        _vision_cache.popitem(last=False)


# ── Capture: screen ──────────────────────────────────────────────────────────

def _mss_to_png_bytes(mss_shot) -> bytes:
    """Convert an mss screenshot object to PNG bytes via Pillow.

    mss returns BGRA frames; Pillow's ``frombytes`` with mode 'RGB' from
    the .rgb buffer gives us a clean image to serialise.
    """
    img = Image.frombytes("RGB", mss_shot.size, mss_shot.rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def capture_screenshot() -> bytes:
    """Capture the primary monitor and return PNG bytes. No temp file."""
    import mss
    with mss.mss() as sct:
        # monitors[1] is the primary monitor; monitors[0] is the bounding box
        # across all monitors (which would be wrong for single-screen capture).
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
    return _mss_to_png_bytes(shot)


def capture_region(x: int, y: int, width: int, height: int) -> bytes:
    """Capture an arbitrary screen rectangle as PNG bytes.

    Raises ``ValueError`` when width or height are not strictly positive —
    mss would otherwise return an empty or wrap-around grab.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"width and height must be positive (got {width}x{height})")
    import mss
    with mss.mss() as sct:
        shot = sct.grab({"left": int(x), "top": int(y),
                         "width": int(width), "height": int(height)})
    return _mss_to_png_bytes(shot)


# ── Capture: webcam ──────────────────────────────────────────────────────────

def capture_webcam(device: int = 0) -> bytes:
    """Capture a single frame from the webcam and return PNG bytes.

    Always releases the device immediately after the read — leaving a
    cv2.VideoCapture open prevents other apps (and subsequent JARVIS
    calls) from using the camera. Converts BGR to RGB before encoding
    because OpenCV uses BGR internally.

    Raises ``RuntimeError`` when the camera can't be opened or the
    first frame read fails.
    """
    import cv2
    cap = cv2.VideoCapture(int(device))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Webcam device {device} not accessible")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Webcam device {device} returned no frame")
    finally:
        cap.release()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Capture: file ────────────────────────────────────────────────────────────

def load_image_file(path: str) -> bytes:
    """Load any Pillow-supported image format and re-encode as PNG bytes.

    Re-encoding (rather than reading the file raw) normalises away
    quirks like EXIF rotation hints and CMYK colour space — the
    Anthropic vision endpoint accepts the PNG cleanly.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    try:
        with Image.open(p) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="PNG")
            return buf.getvalue()
    except (OSError, Image.UnidentifiedImageError) as exc:
        raise ValueError(f"Not a valid image file: {path} ({exc})") from exc


# ── Capture: browser ─────────────────────────────────────────────────────────

def capture_browser_page() -> bytes:
    """Screenshot the active Playwright page from the running session.

    Reuses the singleton ``BrowserSession`` from ``core.browser`` — we
    never spawn a new browser here. Raises ``RuntimeError`` when no
    session is open or no page is active so the caller can surface a
    useful error instead of a Playwright traceback.
    """
    from core.browser import browser as _browser_session
    page = getattr(_browser_session, "_page", None)
    if page is None or not getattr(_browser_session, "_context", None):
        raise RuntimeError("No active browser page")
    try:
        # full_page=False so we get the viewport the user can actually see —
        # vision analysis on a 20 000-px-tall scrolled page is wasteful.
        png_bytes = page.screenshot(type="png", full_page=False)
    except Exception as exc:
        raise RuntimeError(f"Browser screenshot failed: {exc}") from exc
    return png_bytes


# ── Analyze ──────────────────────────────────────────────────────────────────

# Spoken-style screen/image description (read aloud via TTS) — brief and
# conversational, not a raw OCR dump or a structured markdown report.
_DESCRIBE_PROMPT = (
    "You are JARVIS, describing what's on the user's screen out loud. Give a "
    "brief, natural description: lead with the gist (what app, page, or screen "
    "it is), then the most notable or relevant things on it. Keep it concise and "
    "conversational, the way you'd tell a friend what you're looking at — aim for "
    "a few sentences. You may use a short bullet list when you're genuinely "
    "listing several distinct items and it makes things clearer, but prefer "
    "flowing prose. Don't use headings, bold, or other markdown symbols, and "
    "don't transcribe every element or line of text — describe what matters, "
    "don't dump everything."
)

_PROMPT_BY_ACTION: dict[str, str] = {
    "describe": _DESCRIBE_PROMPT,
    "read_text": (
        "Extract and return ALL readable text from this image exactly "
        "as it appears. Preserve formatting where possible."
    ),
    "screenshot_and_describe": _DESCRIBE_PROMPT,
}


def _build_prompt(action: str, question: str) -> str:
    """Resolve action + optional question into the text prompt body."""
    action = (action or "").strip() or "describe"
    question = (question or "").strip()

    if action == "find_ui_element":
        target = question or "the element described by the user"
        return (
            f"Find this UI element on screen: {target}. Reply in one or two short "
            "spoken sentences saying where it is in plain words (e.g. top-right, "
            "near the profile) with approximate x,y coordinates. If there are a "
            "couple, mention each briefly. No markdown, headings, or bullet "
            "lists — just say it the way you'd tell someone out loud."
        )
    if action == "answer_question":
        return question or _PROMPT_BY_ACTION["describe"]
    return _PROMPT_BY_ACTION.get(action, _PROMPT_BY_ACTION["describe"])


def _get_client():
    """Reuse the Anthropic singleton from core.brain.

    Lazy-imported so this module can be imported in environments without
    Anthropic configured (e.g. early test collection) — the brain client
    factory is the same one used by routing, so we share its cache /
    key-invalidation behaviour for free.
    """
    from core.brain import _get_client as _brain_get_client
    return _brain_get_client()


def analyze_image(image_bytes: bytes, question: str = "", action: str = "describe") -> str:
    """Send image bytes to Claude vision and return the analysis text.

    Cache hits short-circuit before the network call. On any SDK error
    we return a short error string rather than raising — the handler
    layer wraps this call with its own try/except too, but a returned
    string keeps the failure path simple.
    """
    if not image_bytes:
        return ""

    # R3-12: fold action + question into the key so different questions about
    # the same image (identical bytes) don't collide and return each other's
    # answers. Pure describe/read_text (no question) still dedupe correctly.
    cache_key = hashlib.sha256(
        image_bytes
        + b"\0" + (action or "").encode("utf-8")
        + b"\0" + (question or "").encode("utf-8")
    ).hexdigest()
    cached = _vision_cache.get(cache_key)
    if cached is not None:
        _dbg("vision", f"cache hit ({len(image_bytes):,} bytes -> {len(cached)} chars)")
        # Touch the entry so it stays warm under FIFO pressure.
        _vision_cache.move_to_end(cache_key)
        return cached

    prompt = _build_prompt(action, question)
    b64_data = base64.b64encode(image_bytes).decode("ascii")

    try:
        client = _get_client()
        response = client.messages.create(
            model=config.claude_model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except Exception as exc:
        _dbg("vision", f"API call failed: {exc}")
        return f"Vision API error: {exc}"

    try:
        text = (response.content[0].text or "").strip()
    except (AttributeError, IndexError, TypeError) as exc:
        _dbg("vision", f"unexpected response shape: {exc}")
        return ""

    if text:
        _cache_put(cache_key, text)
    return text
