"""
Session Video & Animated GIF Recorder for TennenAnchor.
Captures window-scoped screen frames during recipe execution,
stamps real-time telemetry HUD overlays, and compiles optimized animated GIFs
for visual proof and regression testing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from core.dpi import get_screen_metrics, ensure_interactive_desktop

logger = logging.getLogger("tennenanchor.recorder")
user32 = ctypes.windll.user32

DEFAULT_RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "recordings"


def is_recorder_available() -> bool:
    """Checks if developer recording dependencies (mss) are installed."""
    try:
        import mss  # noqa: F401
        return True
    except ImportError:
        return False


class WindowScopedRecorder:
    """
    Non-blocking window-scoped session recorder.
    Captures only the target application's window rectangle (preserving privacy),
    overlays step-by-step execution telemetry, and generates an optimized animated GIF.
    """

    def __init__(
        self,
        hwnd: Optional[int] = None,
        fps: float = 4.0,
        max_width: int = 800,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.hwnd = hwnd
        self.fps = max(1.0, min(15.0, fps))
        self.max_width = max_width
        self.output_dir = output_dir or DEFAULT_RECORDINGS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._raw_frames: List[Tuple[Image.Image, str]] = []
        self._current_status: str = "Initializing"
        self._lock = threading.Lock()
        self._is_stopped: bool = False
        self._compiled_gif: Optional[Path] = None

    def set_hwnd(self, hwnd: int) -> None:
        """Dynamically binds or rebinds the target window handle."""
        self.hwnd = hwnd

    def set_status(self, status: str) -> None:
        """Updates the active HUD banner status text stamped on upcoming frames."""
        with self._lock:
            self._current_status = status

    def get_status(self) -> str:
        with self._lock:
            return self._current_status

    def start(self) -> WindowScopedRecorder:
        """Starts the background frame capture loop."""
        ensure_interactive_desktop()
        self._stop_event.clear()
        self._is_stopped = False
        self._compiled_gif = None
        with self._lock:
            self._raw_frames = []
        self._thread = threading.Thread(target=self._capture_worker, daemon=True)
        self._thread.start()
        logger.info("WindowScopedRecorder started (FPS: %.1f, HWND: %s)", self.fps, self.hwnd)
        return self

    def _get_target_bbox(self) -> Optional[Dict[str, int]]:
        """Computes physical bounding box for the pinned HWND, or falls back to desktop."""
        if (
            self.hwnd
            and user32.IsWindow(self.hwnd)
            and not user32.IsIconic(self.hwnd)
            and user32.IsWindowVisible(self.hwnd)
        ):
            rect = wintypes.RECT()
            if user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 50 and h > 50:
                    return {
                        "left": rect.left,
                        "top": rect.top,
                        "width": w,
                        "height": h,
                    }

        # Fallback to primary screen
        metrics = get_screen_metrics()
        return {
            "left": metrics["left"],
            "top": metrics["top"],
            "width": metrics["width"],
            "height": metrics["height"],
        }

    def _capture_worker(self) -> None:
        """Background thread that captures window frames at the specified FPS."""
        ensure_interactive_desktop()
        try:
            import mss
        except ImportError:
            logger.error("mss package missing; cannot record session")
            return

        interval = 1.0 / self.fps

        try:
            sct_cls = getattr(mss, "MSS", mss.mss)
            with sct_cls() as sct:
                while not self._stop_event.is_set():
                    t0 = time.perf_counter()

                    bbox = self._get_target_bbox()
                    if bbox:
                        try:
                            sct_img = sct.grab(bbox)
                            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                            current_st = self.get_status()
                            with self._lock:
                                self._raw_frames.append((img, current_st))
                        except Exception as grab_err:
                            logger.debug("Frame grab transient error: %s", grab_err)

                    dt = time.perf_counter() - t0
                    sleep_time = interval - dt
                    if sleep_time > 0:
                        self._stop_event.wait(timeout=sleep_time)
        except Exception as sct_err:
            logger.warning("Session recorder capture worker stopped: %s", sct_err)

    def stop(self, filename_prefix: str = "session") -> Optional[Path]:
        """
        Stops capture, renders HUD banners, optimizes frames, and exports animated GIF.
        Returns the Path to the compiled GIF, or None if no frames were captured.
        Thread-safe and idempotent.
        """
        if self._is_stopped and self._compiled_gif:
            return self._compiled_gif

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            frames_to_process = list(self._raw_frames)

        if not frames_to_process:
            logger.warning("WindowScopedRecorder: No frames captured during session.")
            self._is_stopped = True
            return None

        t0 = time.perf_counter()
        logger.info("WindowScopedRecorder: Processing %d captured frames...", len(frames_to_process))

        processed: List[Image.Image] = []

        for raw_img, status_text in frames_to_process:
            w, h = raw_img.size
            if w <= 0 or h <= 0:
                continue

            # Downscale preserving aspect ratio
            if w > self.max_width:
                scale = self.max_width / float(w)
                new_w = self.max_width
                new_h = max(1, int(h * scale))
                frame = raw_img.resize((new_w, new_h), Image.Resampling.BILINEAR)
            else:
                frame = raw_img.copy()
                new_w, new_h = w, h

            # Render Telemetry HUD Banner at bottom
            draw = ImageDraw.Draw(frame)
            banner_height = 24
            banner_top = max(0, new_h - banner_height)

            # Dark translucent banner
            draw.rectangle([(0, banner_top), (new_w, new_h)], fill=(18, 22, 30))

            # Cyan status indicator pill
            draw.rectangle([(6, banner_top + 5), (14, banner_top + 18)], fill=(0, 230, 160))

            # Telemetry text
            hud_text = f"TennenAnchor | {status_text}"
            draw.text((20, banner_top + 4), hud_text, fill=(240, 245, 255))

            # Convert to adaptive palette mode for compact GIF size
            frame_p = frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
            processed.append(frame_p)

        if not processed:
            self._is_stopped = True
            return None

        timestamp = int(time.time() * 1000)
        clean_prefix = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in filename_prefix)
        out_filename = f"{clean_prefix}_{timestamp}.gif"
        out_path = self.output_dir / out_filename

        frame_duration = int(1000.0 / self.fps)

        # Save animated GIF
        try:
            processed[0].save(
                out_path,
                save_all=True,
                append_images=processed[1:],
                duration=frame_duration,
                loop=0,
                disposal=2,
                optimize=False,
            )
        except Exception as save_err:
            logger.error("Failed to compile animated GIF to %s: %s", out_path, save_err)
            self._is_stopped = True
            return None

        dt_proc = (time.perf_counter() - t0) * 1000.0
        file_size_kb = out_path.stat().st_size / 1024.0
        logger.info("WindowScopedRecorder: Compiled %s (%.1f KB, %d frames) in %.1fms",
                    out_path.name, file_size_kb, len(processed), dt_proc)

        with self._lock:
            self._raw_frames.clear()

        self._is_stopped = True
        self._compiled_gif = out_path
        return out_path

    def __enter__(self) -> WindowScopedRecorder:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
