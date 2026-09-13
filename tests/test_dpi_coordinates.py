"""Unit tests for DPI awareness and coordinate transformation."""

import pytest
from core.dpi import init_dpi_awareness, get_screen_metrics, transform_to_screen_coords, is_coordinate_within_screen


def test_dpi_initialization():
    """Verifies that DPI awareness initializes successfully on Windows."""
    success = init_dpi_awareness()
    assert success is True


def test_screen_metrics():
    """Verifies screen metrics return valid desktop dimensions."""
    metrics = get_screen_metrics()
    assert "width" in metrics and metrics["width"] > 0
    assert "height" in metrics and metrics["height"] > 0
    assert "monitors" in metrics and metrics["monitors"] >= 1


def test_normalized_coordinate_transformation():
    """Verifies [0, 1000] normalized coordinates map accurately to physical pixels."""
    # Screen rect: left=0, top=0, width=1920, height=1080
    screen_rect = (0, 0, 1920, 1080)

    # Top-left (0, 0)
    tx, ty = transform_to_screen_coords(0, 0, screen_rect, is_normalized=True)
    assert tx == 0 and ty == 0

    # Center (500, 500)
    tx, ty = transform_to_screen_coords(500, 500, screen_rect, is_normalized=True)
    assert tx == 960 and ty == 540

    # Bottom-right (1000, 1000)
    tx, ty = transform_to_screen_coords(1000, 1000, screen_rect, is_normalized=True)
    assert tx == 1920 and ty == 1080


def test_downscaled_pixel_coordinate_transformation():
    """Verifies downscaled image pixels (e.g. 1280x720) map back to physical 4K / 1080p."""
    # Screen rect: left=100, top=50, width=1920, height=1080
    screen_rect = (100, 50, 1920, 1080)
    img_size = (960, 540)  # 2x downscaled

    # Point at (480, 270) in downscaled image
    tx, ty = transform_to_screen_coords(480, 270, screen_rect, img_size=img_size, is_normalized=False)
    assert tx == 100 + 960  # 1060
    assert ty == 50 + 540   # 590


def test_multi_monitor_bounds_validation():
    """Verifies coordinate validation respects desktop bounds."""
    metrics = get_screen_metrics()
    # (0, 0) should be valid on any desktop
    assert is_coordinate_within_screen(0, 0) is True
    # Absurd coordinate outside any display
    assert is_coordinate_within_screen(999999, 999999) is False
