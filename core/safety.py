"""
Safety and system protection module for Desktop Control Harness.
Prevents suicide clicks on the AGY CLI window, catches fail-safe triggers, and detects UIPI elevation.
"""

import os
import sys
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import psutil

logger = logging.getLogger("desktop_harness.safety")

# Cache protected PIDs (this process, parent process / AGY CLI)
_PROTECTED_PIDS: Set[int] = set()


def get_protected_pids() -> Set[int]:
    """Returns set of PIDs that must NEVER be closed or forcefully manipulated."""
    global _PROTECTED_PIDS
    if not _PROTECTED_PIDS:
        try:
            current_pid = os.getpid()
            _PROTECTED_PIDS.add(current_pid)
            parent = psutil.Process(current_pid).parent()
            if parent:
                _PROTECTED_PIDS.add(parent.pid)
                # If parent is a subshell (cmd/powershell), check grandparent (e.g. terminal / agy)
                grandparent = parent.parent()
                if grandparent:
                    _PROTECTED_PIDS.add(grandparent.pid)
        except Exception as e:
            logger.warning("Could not trace parent process tree: %s", e)
    return _PROTECTED_PIDS


def is_window_protected(hwnd: int) -> bool:
    """Checks if a given window handle belongs to AGY CLI or this harness."""
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in get_protected_pids():
            return True
    except Exception:
        pass
    return False


class ActionRiskLevel:
    READ = "READ"                          # Zero side-effects (inspect, query, screenshot)
    LOW_RISK_WRITE = "LOW_RISK_WRITE"      # Reversible input (type, click, scroll)
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"    # State-modifying / file-altering (hotkey, close, execute)
    CRITICAL_BLOCKED = "CRITICAL_BLOCKED"  # OS-level violation or agent suicide


def classify_action_risk(
    action_name: str,
    hwnd: Optional[int] = None,
    keys: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Classifies the operational risk of a planned desktop action.
    Returns dict with risk level ('READ', 'LOW_RISK_WRITE', 'HIGH_RISK_WRITE', 'CRITICAL_BLOCKED')
    and validation status.
    """
    safe, reason = validate_target_action(hwnd, action_name, keys)
    if not safe:
        return {
            "risk": ActionRiskLevel.CRITICAL_BLOCKED,
            "allowed": False,
            "reason": reason,
        }

    act = action_name.lower().strip()
    if act in ("inspect", "screenshot", "query", "ast", "struggles", "read"):
        return {"risk": ActionRiskLevel.READ, "allowed": True, "reason": "Read-only inspection"}

    if act in ("move", "scroll", "click", "double_click", "right_click", "type", "press_key"):
        return {"risk": ActionRiskLevel.LOW_RISK_WRITE, "allowed": True, "reason": "Standard UI interaction"}

    if act in ("hotkey", "close", "drag", "recipe", "execute", "terminate"):
        return {"risk": ActionRiskLevel.HIGH_RISK_WRITE, "allowed": True, "reason": "State-modifying action"}

    return {"risk": ActionRiskLevel.LOW_RISK_WRITE, "allowed": True, "reason": "Unclassified action default"}


def validate_target_action(hwnd: Optional[int], action_name: str, keys: Optional[list] = None) -> Tuple[bool, str]:
    """
    Validates if an action is safe to execute.
    Blocks closing the AGY CLI terminal window or dangerous system hotkeys.
    """
    if hwnd and is_window_protected(hwnd):
        if action_name in ("close", "terminate"):
            return False, "SAFETY_BLOCKED: Cannot close the AGY CLI terminal window."
        if action_name == "hotkey" and keys:
            normalized_keys = [str(k).lower().strip() for k in keys]
            if "alt" in normalized_keys and "f4" in normalized_keys:
                return False, "SAFETY_BLOCKED: Alt+F4 on AGY CLI terminal is forbidden."

    # General dangerous hotkey filter
    if action_name == "hotkey" and keys:
        norm = [str(k).lower().strip() for k in keys]
        if "ctrl" in norm and "alt" in norm and "del" in norm:
            return False, "SAFETY_BLOCKED: Ctrl+Alt+Del cannot be synthesized."

    return True, ""


def is_process_elevated(pid: int) -> bool:
    """Checks if a target process is running as Administrator (UIPI warning)."""
    try:
        import win32process
        import win32security
        import win32con

        h_proc = win32process.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        token = win32security.OpenProcessToken(h_proc, win32con.TOKEN_QUERY)
        elevation = win32security.GetTokenInformation(token, win32security.TokenElevation)
        return bool(elevation)
    except Exception:
        return False
