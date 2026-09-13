"""Unit tests for Tier 1 Edge parser and Tier 2 Screenshot escalator."""

import os
import pytest
from perception.edge_parser import EdgeUIAParser
from perception.screenshot_escalator import ScreenshotEscalator


def test_edge_parser_formatting():
    """Verifies that format_compact_text produces concise token-efficient output."""
    parser = EdgeUIAParser()
    mock_result = {
        "status": "ok",
        "window": "Calculator",
        "hwnd": 12345,
        "rect": (100, 100, 400, 600),
        "elements": [
            {"id": 1, "name": "One", "type": "Btn", "center": (150, 200), "rect": (120, 180, 180, 220), "focused": False},
            {"id": 2, "name": "Two", "type": "Btn", "center": (250, 200), "rect": (220, 180, 280, 220), "focused": False},
            {"id": 3, "name": "Display", "type": "Edit", "center": (200, 150), "rect": (120, 130, 280, 170), "focused": True},
        ]
    }
    text = parser.format_compact_text(mock_result)
    assert "[ACTIVE: \"Calculator\"" in text
    assert "#1 [Btn \"One\"] @(150,200)" in text
    assert "#3 [Edit \"Display\"] @(200,150) [FOCUSED]" in text
    # Verify token footprint is extremely small (under 80 words)
    assert len(text.split()) < 80


def test_edge_parser_escalation_recommendation():
    """Verifies format_compact_text cleanly handles escalation trigger."""
    parser = EdgeUIAParser()
    mock_escalate = {
        "status": "escalate",
        "reason": "Zero interactive UIA controls found in foreground window.",
        "window": "GameWindow",
        "elements": []
    }
    text = parser.format_compact_text(mock_escalate)
    assert "[PERCEPTION: ESCALATE TO VISION]" in text
    assert "desktop_escalate()" in text


def test_screenshot_escalator_capture():
    """Verifies screenshot capture runs, saves file, and downscales correctly."""
    escalator = ScreenshotEscalator(max_dimension=1280)
    res = escalator.capture(target="full_screen")
    assert res["status"] == "ok"
    assert os.path.exists(res["image_path"])
    assert res["scaled_size"][0] <= 1280
    assert res["scaled_size"][1] <= 1280
    assert len(res["base64_image"]) > 100
    # Clean up after test
    ScreenshotEscalator.cleanup_old_screenshots(max_keep=0)


def test_screenshot_cleanup():
    """Verifies that cleanup_old_screenshots correctly prunes files above threshold."""
    import time
    from perception.screenshot_escalator import OUTPUT_DIR

    ScreenshotEscalator.cleanup_old_screenshots(max_keep=0)
    for i in range(7):
        dummy = OUTPUT_DIR / f"dummy_{i}.png"
        dummy.write_text("test")
        time.sleep(0.01)

    assert len(list(OUTPUT_DIR.glob("*.png"))) == 7
    deleted = ScreenshotEscalator.cleanup_old_screenshots(max_keep=3)
    assert deleted == 4
    assert len(list(OUTPUT_DIR.glob("*.png"))) == 3

    # Clean up completely
    ScreenshotEscalator.cleanup_old_screenshots(max_keep=0)
    assert len(list(OUTPUT_DIR.glob("*.png"))) == 0
