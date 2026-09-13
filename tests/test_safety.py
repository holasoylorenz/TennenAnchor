"""Unit tests for safety filters and AGY CLI self-preservation."""

import os
import pytest
from core.safety import get_protected_pids, is_window_protected, validate_target_action


def test_protected_pids():
    """Verifies that the current process PID is in the protected set."""
    pids = get_protected_pids()
    assert os.getpid() in pids


def test_validate_target_action_dangerous_hotkeys():
    """Verifies that Ctrl+Alt+Del is blocked."""
    safe, reason = validate_target_action(None, "hotkey", ["ctrl", "alt", "del"])
    assert safe is False
    assert "SAFETY_BLOCKED" in reason


def test_validate_target_action_safe_hotkeys():
    """Verifies that standard productivity hotkeys are permitted."""
    safe, reason = validate_target_action(None, "hotkey", ["ctrl", "c"])
    assert safe is True
    assert reason == ""

    safe, reason = validate_target_action(None, "hotkey", ["win", "r"])
    assert safe is True
    assert reason == ""
