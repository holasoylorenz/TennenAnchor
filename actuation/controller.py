"""
Unified Actuation Controller for Windows Desktop Automation.
Provides safe, DPI-aware mouse and keyboard actions with window focus management and fail-safe recovery.
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from core.dpi import init_dpi_awareness, transform_to_screen_coords, is_coordinate_within_screen
from core.safety import validate_target_action

logger = logging.getLogger("desktop_harness.controller")


class DesktopController:
    """Controls mouse cursor, clicks, text typing, and keypresses on Windows."""

    def __init__(self, pause_sec: float = 0.08):
        init_dpi_awareness()
        self.pause_sec = pause_sec
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = pause_sec
        except ImportError:
            pass

    @staticmethod
    def is_window_or_descendant(fg: int, target_hwnd: int) -> bool:
        """Returns True if fg is target_hwnd or an owned/child dialog or same process."""
        if not fg or not target_hwnd:
            return False
        if fg == target_hwnd:
            return True

        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        # Check owner / parent chain
        curr = fg
        for _ in range(5):
            owner = user32.GetWindow(curr, 4)  # GW_OWNER
            parent = user32.GetParent(curr)
            if owner == target_hwnd or parent == target_hwnd:
                return True
            curr = owner or parent
            if not curr:
                break

        # Check process ID
        pid_fg = wintypes.DWORD()
        pid_target = wintypes.DWORD()
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid_fg))
        user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(pid_target))
        if pid_fg.value > 0 and pid_fg.value == pid_target.value:
            return True

        return False

    def force_focus_window(self, hwnd: int, allow_descendant: bool = False) -> bool:
        """
        Robust Win32 foreground attachment.
        Attaches thread input queues, un-minimizes window, and asserts focus.
        If allow_descendant is True, already focused modal dialogs belonging to hwnd are preserved.
        """
        try:
            import win32gui
            import win32process
            import win32api
            import win32con

            fg = win32gui.GetForegroundWindow()
            if fg == hwnd:
                return True
            if allow_descendant and self.is_window_or_descendant(fg, hwnd):
                return True

            cur_tid = win32api.GetCurrentThreadId()
            target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)

            attached = False
            if cur_tid != target_tid:
                win32process.AttachThreadInput(cur_tid, target_tid, True)
                attached = True

            try:
                # Simulate menu key press to unblock SetForegroundWindow
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.05)
                return True
            finally:
                if attached:
                    win32process.AttachThreadInput(cur_tid, target_tid, False)
        except Exception as e:
            logger.debug("force_focus_window failed for hwnd %s: %s", hwnd, e)
            return False

    def click(self, x: int, y: int, button: str = "left") -> Dict[str, Any]:
        """Performs mouse click at physical screen coordinate (x, y)."""
        import pyautogui

        if not is_coordinate_within_screen(x, y):
            return {
                "status": "error",
                "error": f"Coordinates ({x}, {y}) are outside physical desktop boundaries.",
            }

        try:
            if button == "double":
                pyautogui.doubleClick(x, y)
            elif button == "right":
                pyautogui.rightClick(x, y)
            elif button == "middle":
                pyautogui.middleClick(x, y)
            else:
                pyautogui.click(x, y)

            return {"status": "ok", "action": f"{button}_click", "at": (x, y)}
        except pyautogui.FailSafeException:
            return {
                "status": "aborted",
                "error": "SAFETY_ABORT: User moved cursor to screen corner to abort.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def move_cursor(self, x: int, y: int) -> Dict[str, Any]:
        """Moves cursor to coordinate (x, y)."""
        import pyautogui

        if not is_coordinate_within_screen(x, y):
            return {
                "status": "error",
                "error": f"Coordinates ({x}, {y}) are outside physical desktop boundaries.",
            }

        try:
            pyautogui.moveTo(x, y, duration=0.15)
            return {"status": "ok", "action": "mouse_move", "at": (x, y)}
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> Dict[str, Any]:
        """Drags mouse from start to end coordinates."""
        import pyautogui

        try:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(end_x, end_y, duration=0.4, button="left")
            return {
                "status": "ok",
                "action": "drag",
                "from": (start_x, start_y),
                "to": (end_x, end_y),
            }
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def scroll(self, clicks: int = 3, direction: str = "down") -> Dict[str, Any]:
        """Scrolls mouse wheel up or down."""
        import pyautogui

        amount = -clicks if direction == "down" else clicks
        try:
            pyautogui.scroll(amount * 120)
            return {"status": "ok", "action": f"scroll_{direction}", "clicks": clicks}
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def type_text(self, text: str, press_enter: bool = False, target_hwnd: Optional[int] = None) -> Dict[str, Any]:
        """Types text with optional enter key. Focuses target window if hwnd is provided."""
        import pyautogui

        if target_hwnd:
            self.force_focus_window(target_hwnd, allow_descendant=True)

        try:
            pyautogui.typewrite(text, interval=0.015)
            if press_enter:
                pyautogui.press("enter")
            return {
                "status": "ok",
                "action": "type",
                "length": len(text),
                "pressed_enter": press_enter,
            }
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def hotkey(self, keys: List[str], target_hwnd: Optional[int] = None) -> Dict[str, Any]:
        """
        Presses a combination of keys (e.g. ['win', 'r'], ['ctrl', 'c'], ['alt', 'tab']).
        Enforces safety filters to prevent terminating the AGY CLI session.
        """
        import pyautogui

        safe, reason = validate_target_action(target_hwnd, "hotkey", keys)
        if not safe:
            return {"status": "error", "error": reason}

        if target_hwnd:
            self.force_focus_window(target_hwnd, allow_descendant=True)

        normalized = [k.strip().lower() for k in keys]
        try:
            pyautogui.hotkey(*normalized)
            time.sleep(0.1)
            return {"status": "ok", "action": "hotkey", "keys": normalized}
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def press_key(self, key: str) -> Dict[str, Any]:
        """Presses a single key (e.g. 'enter', 'esc', 'tab', 'backspace')."""
        import pyautogui

        k = key.strip().lower()
        try:
            pyautogui.press(k)
            return {"status": "ok", "action": "press_key", "key": k}
        except pyautogui.FailSafeException:
            return {"status": "aborted", "error": "SAFETY_ABORT: Fail-safe triggered."}
        except Exception as e:
            return {"status": "error", "error": str(e)}
