"""
Tier 2 Visual Escalation Engine for Windows Desktop Automation.
Captures screen/window via mss, applies intelligent downscaling (max 1280px) and compression (quality 80)
to constrain Gemini vision tokens (~600-800 tokens), and outputs coordinate transformation metadata.
"""

import os
import time
import base64
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from core.dpi import init_dpi_awareness, get_screen_metrics, ensure_interactive_desktop

logger = logging.getLogger("desktop_harness.escalator")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "screenshots"


class ScreenshotEscalator:
    """Captures and optimizes screenshots for Tier 2 multimodal AI vision."""

    def __init__(self, max_dimension: int = 1280, quality: int = 80):
        self.max_dimension = max_dimension
        self.quality = quality
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        init_dpi_awareness()

    def capture(self, target: str = "active_window", hwnd: Optional[int] = None) -> Dict[str, Any]:
        """
        Captures screenshot of either 'active_window' or 'full_screen'.
        Returns:
            Dict containing:
                - status: 'ok' or 'error'
                - image_path: path to saved compressed image
                - base64_image: base64 encoded string
                - original_rect: (left, top, width, height) in physical screen coords
                - scaled_size: (width, height) of the downscaled image
                - normalized_supported: True (can use [0, 1000] coordinates)
        """
        ensure_interactive_desktop()
        try:
            import mss
            from PIL import Image
        except ImportError as e:
            return {
                "status": "error",
                "reason": f"Missing screen capture dependencies (mss/PIL): {e}",
            }

        screen_metrics = get_screen_metrics()

        capture_bbox = None
        target_name = "Desktop"

        if target == "active_window" and hwnd:
            try:
                import win32gui
                rect = win32gui.GetWindowRect(hwnd)
                # left, top, right, bottom
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w > 50 and h > 50:
                    capture_bbox = {
                        "left": rect[0],
                        "top": rect[1],
                        "width": w,
                        "height": h,
                    }
                    target_name = win32gui.GetWindowText(hwnd) or "ActiveWindow"
            except Exception as e:
                logger.warning("Could not get window rect for hwnd %s: %s", hwnd, e)

        # Fallback to full virtual desktop
        if not capture_bbox:
            capture_bbox = {
                "left": screen_metrics["left"],
                "top": screen_metrics["top"],
                "width": screen_metrics["width"],
                "height": screen_metrics["height"],
            }

        timestamp = int(time.time() * 1000)
        filename = f"escalation_{timestamp}.png"
        filepath = OUTPUT_DIR / filename

        with mss.MSS() as sct:
            sct_img = sct.grab(capture_bbox)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        orig_w, orig_h = img.size

        # Downscale to max_dimension preserving aspect ratio
        scale_factor = 1.0
        if orig_w > self.max_dimension or orig_h > self.max_dimension:
            if orig_w >= orig_h:
                scale_factor = self.max_dimension / float(orig_w)
            else:
                scale_factor = self.max_dimension / float(orig_h)

            new_w = max(1, int(orig_w * scale_factor))
            new_h = max(1, int(orig_h * scale_factor))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            new_w, new_h = orig_w, orig_h

        # Save with quality optimization
        img.save(filepath, format="PNG", optimize=True)

        # Generate base64
        with open(filepath, "rb") as f:
            encoded_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "ok",
            "image_path": str(filepath),
            "base64_image": encoded_b64,
            "target": target_name,
            "original_rect": (
                capture_bbox["left"],
                capture_bbox["top"],
                capture_bbox["width"],
                capture_bbox["height"],
            ),
            "scaled_size": (new_w, new_h),
            "scale_factor": scale_factor,
            "normalized_supported": True,
            "prompt_hint": (
                f"Screenshot saved to: {filepath.name}\n"
                f"Target: \"{target_name}\" ({orig_w}x{orig_h} downscaled to {new_w}x{new_h}).\n"
                f"Coordinates: Provide clicks as either normalized [0, 1000] coords or image pixels."
            ),
        }
