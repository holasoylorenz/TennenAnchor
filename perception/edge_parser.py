"""
Tier 1 Edge AI Screen Parser for Windows Desktop Automation.
Uses Windows UI Automation (uiautomation) to extract interactive controls in <35ms.
Features threaded timeout protection (2.0s), control filtering, and ultra-compact formatting.
"""

import sys
import logging
import concurrent.futures
from typing import Dict, List, Optional, Any

from core.dpi import init_dpi_awareness, ensure_interactive_desktop

logger = logging.getLogger("desktop_harness.edge_parser")

# Target control types that an agent can interact with
INTERACTIVE_CONTROL_TYPES = {
    "ButtonControl": "Btn",
    "EditControl": "Edit",
    "MenuItemControl": "Menu",
    "CheckBoxControl": "Check",
    "RadioButtonControl": "Radio",
    "ComboBoxControl": "Combo",
    "TabItemControl": "Tab",
    "HyperlinkControl": "Link",
    "ListItemControl": "Item",
    "TreeItemControl": "Tree",
}

# Max elements to return in a standard summary to keep token count minimal
DEFAULT_MAX_ELEMENTS = 35


class EdgeUIAParser:
    """
    Tier 1 Edge Parser: Walks the active foreground window using Windows UI Automation.
    Returns a compact list of interactable controls with their assigned IDs and coordinates.
    """

    def __init__(self, timeout_sec: float = 2.0, max_elements: int = DEFAULT_MAX_ELEMENTS):
        self.timeout_sec = timeout_sec
        self.max_elements = max_elements
        self.last_cache: Dict[int, Dict[str, Any]] = {}
        self.last_window_info: Dict[str, Any] = {}
        init_dpi_awareness()

    def parse_active_window(self, query: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses the active foreground window within a strict timeout.
        If the call times out or finds 0 interactive controls, returns an 'escalate' status.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._crawl_foreground_window, query)
            try:
                result = future.result(timeout=self.timeout_sec)
                # If parsed successfully, cache elements for subsequent click_element calls
                if result.get("status") == "ok":
                    self.last_cache = {el["id"]: el for el in result.get("elements", [])}
                    self.last_window_info = {
                        "name": result.get("window"),
                        "hwnd": result.get("hwnd"),
                        "rect": result.get("rect"),
                    }
                return result
            except concurrent.futures.TimeoutError:
                logger.warning("UIA crawl timed out (> %ss); recommending escalation.", self.timeout_sec)
                return {
                    "status": "escalate",
                    "reason": f"UIA tree crawl timed out ({self.timeout_sec}s). Application may be unresponsive or rendered via non-UIA canvas.",
                    "window": "Unknown (timeout)",
                    "elements": [],
                }
            except Exception as e:
                logger.warning("UIA crawl encountered error: %s", e)
                return {
                    "status": "escalate",
                    "reason": f"UIA error: {str(e)}",
                    "window": "Error",
                    "elements": [],
                }

    def _crawl_foreground_window(self, query: Optional[str] = None) -> Dict[str, Any]:
        """Internal synchronous crawl of the foreground window."""
        ensure_interactive_desktop()
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
        try:
            import uiautomation as auto
        except ImportError:
            return {
                "status": "escalate",
                "reason": "uiautomation library is not installed.",
                "elements": [],
            }

        auto.SetGlobalSearchTimeout(1.0)
        fg_window = auto.GetForegroundControl()
        if not fg_window:
            return {
                "status": "escalate",
                "reason": "No active foreground window detected.",
                "elements": [],
            }

        win_rect = fg_window.BoundingRectangle
        win_info = {
            "name": fg_window.Name.strip() if fg_window.Name else "<Untitled Window>",
            "hwnd": fg_window.NativeWindowHandle,
            "rect": (win_rect.left, win_rect.top, win_rect.width(), win_rect.height()),
        }

        elements: List[Dict[str, Any]] = []
        query_lower = query.lower().strip() if query else None

        try:
            for curr_ctrl, depth in auto.WalkControl(fg_window, includeTop=False, maxDepth=4):
                if len(elements) >= self.max_elements:
                    break
                try:
                    rect = curr_ctrl.BoundingRectangle
                    c_type = curr_ctrl.ControlTypeName
                    name = curr_ctrl.Name.strip() if curr_ctrl.Name else ""

                    if rect.width() > 4 and rect.height() > 4 and not curr_ctrl.IsOffscreen:
                        if c_type in INTERACTIVE_CONTROL_TYPES:
                            matches_query = True
                            if query_lower:
                                matches_query = (query_lower in name.lower()) or (query_lower in c_type.lower())

                            if matches_query:
                                el_id = len(elements) + 1
                                center_x = rect.left + (rect.width() // 2)
                                center_y = rect.top + (rect.height() // 2)
                                elements.append({
                                    "id": el_id,
                                    "name": name or "<unnamed>",
                                    "type": INTERACTIVE_CONTROL_TYPES[c_type],
                                    "center": (center_x, center_y),
                                    "rect": (rect.left, rect.top, rect.right, rect.bottom),
                                    "focused": bool(curr_ctrl.HasKeyboardFocus),
                                })
                except Exception:
                    pass
        except Exception as e:
            logger.debug("WalkControl traversal exception: %s", e)

        if not elements and not query:
            # 0 elements found in foreground window: automatic escalation trigger
            return {
                "status": "escalate",
                "reason": "Zero interactive UIA controls found in foreground window (likely custom canvas/DirectX/web-app).",
                "window": win_info["name"],
                "hwnd": win_info["hwnd"],
                "rect": win_info["rect"],
                "elements": [],
            }

        return {
            "status": "ok",
            "window": win_info["name"],
            "hwnd": win_info["hwnd"],
            "rect": win_info["rect"],
            "elements": elements,
        }

    def format_compact_text(self, result: Dict[str, Any], delta_only: bool = False) -> str:
        """
        Converts parsed elements into an ultra-compact string (~30-100 tokens)
        designed to never bloat AGY CLI's conversation context.
        If delta_only=True and active window is unchanged, emits a delta summary (~15 tokens).
        """
        if result.get("status") == "escalate":
            return (
                f"[PERCEPTION: ESCALATE TO VISION]\n"
                f"Window: \"{result.get('window', 'Unknown')}\"\n"
                f"Reason: {result.get('reason', 'Edge parsing unavailable')}\n"
                f"Recommendation: Call desktop_escalate() to capture and visually inspect the screen."
            )

        win_name = result.get("window", "Unknown")
        rect = result.get("rect", (0, 0, 0, 0))
        elements = result.get("elements", [])

        # Smart Delta Compression: If window HWND has not changed, summarize delta
        if delta_only and self.last_window_info.get("hwnd") and self.last_window_info.get("hwnd") == result.get("hwnd"):
            focused = [el for el in elements if el.get("focused")]
            foc_str = f"Focused: #{focused[0]['id']} [{focused[0]['type']} '{focused[0]['name']}']" if focused else "Focused: None"
            return f"[ACTIVE: \"{win_name}\" | Delta: Unchanged | {foc_str} | Active Controls: {len(elements)}]"

        lines = [f"[ACTIVE: \"{win_name}\" | Rect: {rect[0]},{rect[1]} {rect[2]}x{rect[3]}]"]
        if not elements:
            lines.append("  (No matching controls found)")
        else:
            for el in elements:
                focused_tag = " [FOCUSED]" if el.get("focused") else ""
                lines.append(
                    f"#{el['id']} [{el['type']} \"{el['name']}\"] @({el['center'][0]},{el['center'][1]}){focused_tag}"
                )

        return "\n".join(lines)
