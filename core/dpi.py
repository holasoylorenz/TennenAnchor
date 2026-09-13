"""
DPI awareness and coordinate transformation module for Windows Desktop Automation.
Ensures perfect alignment between mss screenshots, UIA bounding boxes, and PyAutoGUI clicks.
"""

import ctypes
import logging
from typing import Tuple, Optional

logger = logging.getLogger("desktop_harness.dpi")

# Cache current DPI state
_DPI_INITIALIZED = False


def ensure_interactive_desktop() -> bool:
    """
    Ensures the current thread is attached to the interactive user input desktop (Default).
    Crucial when running in background shells, services, or sandboxed agent environments.
    """
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            return bool(user32.SetThreadDesktop(hdesk))
    except Exception:
        pass
    return False


def init_dpi_awareness() -> bool:
    """
    Initializes Per-Monitor v2 DPI Awareness on Windows and attaches to the interactive desktop.
    This guarantees that GetSystemMetrics, mss screen capture, Windows UI Automation,
    and PyAutoGUI all operate in the exact same physical pixel coordinate space.
    """
    global _DPI_INITIALIZED
    ensure_interactive_desktop()
    if _DPI_INITIALIZED:
        return True

    # Try DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (-4)
    try:
        res = ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        if res:
            logger.info("Initialized Per-Monitor v2 DPI awareness.")
            _DPI_INITIALIZED = True
            return True
    except Exception as e:
        logger.debug("SetProcessDpiAwarenessContext failed: %s", e)

    # Fallback to SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE = 2)
    try:
        res = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if res == 0:  # S_OK
            logger.info("Initialized Per-Monitor DPI awareness via shcore.")
            _DPI_INITIALIZED = True
            return True
    except Exception as e:
        logger.debug("SetProcessDpiAwareness failed: %s", e)

    # Fallback to SetProcessDPIAware()
    try:
        res = ctypes.windll.user32.SetProcessDPIAware()
        if res:
            logger.info("Initialized System DPI awareness.")
            _DPI_INITIALIZED = True
            return True
    except Exception as e:
        logger.warning("Failed to initialize any DPI awareness: %s", e)

    return False


def get_screen_metrics() -> dict:
    """
    Retrieves the virtual desktop metrics covering all monitors.
    Returns:
        dict with left, top, width, height, is_multi_monitor.
    """
    init_dpi_awareness()
    user32 = ctypes.windll.user32
    # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77
    # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
    # SM_CMONITORS = 80
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    monitors_count = user32.GetSystemMetrics(80)

    # Fallback to primary monitor if virtual metrics returned 0
    if width <= 0 or height <= 0:
        width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        left = 0
        top = 0

    return {
        "left": left,
        "top": top,
        "width": width,
        "height": height,
        "monitors": monitors_count,
    }


def is_coordinate_within_screen(x: int, y: int) -> bool:
    """
    Validates if coordinate (x, y) is within the physical desktop bounds,
    correctly supporting negative coordinates for secondary monitors.
    """
    metrics = get_screen_metrics()
    in_x = metrics["left"] <= x <= (metrics["left"] + metrics["width"])
    in_y = metrics["top"] <= y <= (metrics["top"] + metrics["height"])
    return in_x and in_y


def transform_to_screen_coords(
    x: float,
    y: float,
    screen_rect: Tuple[int, int, int, int],
    img_size: Optional[Tuple[int, int]] = None,
    is_normalized: bool = False,
) -> Tuple[int, int]:
    """
    Transforms coordinates from AI Vision downscaled or normalized space
    back to physical Windows screen pixels.

    Args:
        x, y: Input coordinates.
        screen_rect: (left, top, width, height) of the captured screen or window.
        img_size: (width, height) of the downscaled screenshot image (if not normalized).
        is_normalized: True if x, y are in [0, 1000] space (standard Gemini vision grounding).

    Returns:
        (target_x, target_y) in physical desktop coordinates.
    """
    s_left, s_top, s_w, s_h = screen_rect

    if is_normalized:
        target_x = s_left + int((x / 1000.0) * s_w)
        target_y = s_top + int((y / 1000.0) * s_h)
    elif img_size is not None and img_size[0] > 0 and img_size[1] > 0:
        img_w, img_h = img_size
        scale_x = s_w / float(img_w)
        scale_y = s_h / float(img_h)
        target_x = s_left + int(x * scale_x)
        target_y = s_top + int(y * scale_y)
    else:
        # Direct pixel offset
        target_x = s_left + int(x)
        target_y = s_top + int(y)

    return target_x, target_y
