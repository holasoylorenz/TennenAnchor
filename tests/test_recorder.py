"""Unit tests for WindowScopedRecorder."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from core.recorder import WindowScopedRecorder


def test_recorder_status_thread_safety():
    """Verifies that status messages update correctly."""
    rec = WindowScopedRecorder()
    assert rec.get_status() == "Initializing"

    rec.set_status("Step 1/2: open_schematic")
    assert rec.get_status() == "Step 1/2: open_schematic"


def test_recorder_compiles_animated_gif(tmp_path: Path):
    """Verifies that processing synthetic frames produces an optimized animated GIF."""
    rec = WindowScopedRecorder(output_dir=tmp_path, fps=5.0, max_width=320)

    # Inject synthetic raw frames
    frame1 = Image.new("RGB", (640, 480), (30, 40, 50))
    frame2 = Image.new("RGB", (640, 480), (60, 80, 100))
    rec._raw_frames = [
        (frame1, "Step 1: open"),
        (frame2, "Step 2: run"),
    ]

    out_gif = rec.stop(filename_prefix="test_recipe")

    assert out_gif is not None
    assert out_gif.exists()
    assert out_gif.suffix == ".gif"
    assert out_gif.stat().st_size > 0

    # Verify Pillow can open the animated GIF and verify frame count
    with Image.open(out_gif) as img:
        assert getattr(img, "is_animated", False)
        assert img.n_frames == 2
        assert img.width == 320  # Resized to max_width


def test_recorder_empty_frames_returns_none(tmp_path: Path):
    """Verifies that stopping with no captured frames returns None cleanly."""
    rec = WindowScopedRecorder(output_dir=tmp_path)
    result = rec.stop()
    assert result is None
