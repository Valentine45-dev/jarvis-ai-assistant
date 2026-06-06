"""Unit tests for core/vision.py and core/handlers/vision_handler.py.

All external surfaces (Anthropic vision API, mss screen grab, cv2
VideoCapture, Playwright session) are mocked — these tests never open
the camera, hit the network, or call into a real Anthropic client.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from unittest.mock import MagicMock, patch

from core import vision
from core.handlers.vision_handler import _handle_vision_analysis


def _make_png_bytes(color: str | tuple = "red", size: tuple[int, int] = (10, 10)) -> bytes:
    """Create minimal valid PNG bytes for testing."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── describe prompt (brief, TTS-friendly) ─────────────────────────────────────


class TestDescribePrompt:
    """`describe` must be the brief, conversational, spoken-style prompt — not the
    old 'describe everything visible' dump (and not raw OCR)."""

    def test_describe_is_the_spoken_summary_prompt(self):
        p = vision._build_prompt("describe", "")
        assert p == vision._DESCRIBE_PROMPT
        low = p.lower()
        assert "jarvis" in low
        assert "out loud" in low
        assert "brief" in low
        assert "don't transcribe" in low and "don't dump everything" in low
        # bullets allowed but only when they help; prose preferred
        assert "bullet" in low and "prefer" in low
        # the old verbose instruction is gone
        assert "describe everything visible" not in low

    def test_screenshot_and_describe_uses_same_prompt(self):
        assert vision._build_prompt("screenshot_and_describe", "") == vision._DESCRIBE_PROMPT

    def test_read_text_stays_verbatim(self):
        p = vision._build_prompt("read_text", "")
        low = p.lower()
        assert "extract" in low and "all" in low      # still verbatim extraction
        assert p != vision._DESCRIBE_PROMPT

    def test_find_ui_element_is_concise_spoken(self):
        p = vision._build_prompt("find_ui_element", "submit button").lower()
        assert "submit button" in p
        assert "find" in p and "spoken" in p
        assert "no markdown" in p          # concise/TTS-friendly, not a markdown report

    def test_answer_question_uses_question(self):
        assert "what color is the logo" in vision._build_prompt(
            "answer_question", "what color is the logo")


# ── load_image_file ──────────────────────────────────────────────────────────


class TestLoadImageFile:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            vision.load_image_file("nonexistent.png")

    def test_valid_png_returns_bytes(self, tmp_path):
        p = tmp_path / "test.png"
        p.write_bytes(_make_png_bytes())
        result = vision.load_image_file(str(p))
        assert isinstance(result, bytes)
        assert len(result) > 0
        # Re-encoded as PNG — magic header
        assert result.startswith(bytes.fromhex("89504e470d0a1a0a"))

    def test_garbage_file_raises_value_error(self, tmp_path):
        p = tmp_path / "not-an-image.png"
        p.write_bytes(b"this is not a PNG")
        with pytest.raises(ValueError):
            vision.load_image_file(str(p))


# ── Cache behaviour ──────────────────────────────────────────────────────────


class TestVisionCache:
    def setup_method(self):
        vision.clear_vision_cache()

    def test_cache_hit_skips_api(self):
        png = _make_png_bytes()
        with patch("core.vision._get_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="a red square")]
            mock_client.return_value.messages.create.return_value = mock_resp

            first = vision.analyze_image(png, "", "describe")
            second = vision.analyze_image(png, "", "describe")

            # API called exactly once for two identical inputs.
            assert mock_client.return_value.messages.create.call_count == 1
            assert first == "a red square"
            assert second == "a red square"

    def test_cache_eviction_at_21(self):
        with patch("core.vision._get_client") as mock_c:
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="x")]
            mock_c.return_value.messages.create.return_value = mock_resp

            for i in range(21):
                # Distinct PNGs => distinct hashes
                vision.analyze_image(
                    _make_png_bytes(color=(i, i, i)), "", "describe"
                )

            assert len(vision._vision_cache) <= 20

    def test_different_images_dont_share_cache(self):
        png_a = _make_png_bytes(color="red")
        png_b = _make_png_bytes(color="blue")
        with patch("core.vision._get_client") as mock_c:
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text="ok")]
            mock_c.return_value.messages.create.return_value = mock_resp

            vision.analyze_image(png_a, "", "describe")
            vision.analyze_image(png_b, "", "describe")
            # Two distinct images → two distinct calls.
            assert mock_c.return_value.messages.create.call_count == 2


# ── Capture region ───────────────────────────────────────────────────────────


class TestCaptureRegion:
    def test_negative_dimensions_raise_value_error(self):
        with pytest.raises(ValueError):
            vision.capture_region(0, 0, -1, -1)

    def test_zero_dimensions_raise_value_error(self):
        with pytest.raises(ValueError):
            vision.capture_region(0, 0, 0, 0)


# ── Handler ──────────────────────────────────────────────────────────────────


class TestVisionHandler:
    def setup_method(self):
        vision.clear_vision_cache()

    def test_file_not_found(self):
        result = _handle_vision_analysis(
            "describe",
            {"source": "file", "path": "nonexistent.png"},
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_missing_path_for_file_source(self):
        result = _handle_vision_analysis(
            "describe",
            {"source": "file", "path": ""},
        )
        assert result["success"] is False
        assert "path" in result["error"].lower()

    def test_missing_region_for_region_source(self):
        result = _handle_vision_analysis(
            "describe",
            {"source": "region"},
        )
        assert result["success"] is False
        assert "region" in result["error"].lower()

    def test_successful_screenshot_analysis(self):
        png = _make_png_bytes()
        with patch("core.vision.capture_screenshot", return_value=png), \
             patch("core.vision.analyze_image", return_value="A red square."):
            result = _handle_vision_analysis(
                "describe",
                {"source": "screenshot"},
            )
        assert result["success"] is True
        assert result["output"] == "A red square."

    def test_successful_webcam_analysis(self):
        png = _make_png_bytes(color="green")
        with patch("core.vision.capture_webcam", return_value=png) as mock_cap, \
             patch("core.vision.analyze_image", return_value="The webcam shows a green square."):
            result = _handle_vision_analysis(
                "describe",
                {"source": "webcam", "device": 1},
            )
        mock_cap.assert_called_once_with(1)
        assert result["success"] is True
        assert "green" in result["output"].lower()

    def test_find_ui_element_passes_question(self):
        png = _make_png_bytes()
        with patch("core.vision.capture_screenshot", return_value=png), \
             patch("core.vision.analyze_image") as mock_analyze:
            mock_analyze.return_value = "Top-right corner."
            result = _handle_vision_analysis(
                "find_ui_element",
                {"source": "screenshot", "question": "submit button"},
            )
        # Handler must forward both the question and the action verbatim.
        args, kwargs = mock_analyze.call_args
        assert args[0] == png
        assert args[1] == "submit button"
        assert args[2] == "find_ui_element"
        assert result["success"] is True

    def test_analyze_exception_returns_err(self):
        png = _make_png_bytes()
        with patch("core.vision.capture_screenshot", return_value=png), \
             patch("core.vision.analyze_image", side_effect=RuntimeError("boom")):
            result = _handle_vision_analysis(
                "describe",
                {"source": "screenshot"},
            )
        assert result["success"] is False
        assert "boom" in result["error"]
