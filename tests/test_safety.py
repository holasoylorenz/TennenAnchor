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


def test_classify_action_risk():
    """Verifies that actions are accurately classified into risk categories."""
    from core.safety import ActionRiskLevel, classify_action_risk

    # READ actions
    r_inspect = classify_action_risk("inspect")
    assert r_inspect["risk"] == ActionRiskLevel.READ
    assert r_inspect["allowed"] is True

    # LOW_RISK_WRITE actions
    r_click = classify_action_risk("click")
    assert r_click["risk"] == ActionRiskLevel.LOW_RISK_WRITE
    assert r_click["allowed"] is True

    # HIGH_RISK_WRITE actions
    r_recipe = classify_action_risk("recipe")
    assert r_recipe["risk"] == ActionRiskLevel.HIGH_RISK_WRITE
    assert r_recipe["allowed"] is True

    # CRITICAL_BLOCKED actions
    r_cad = classify_action_risk("hotkey", keys=["ctrl", "alt", "del"])
    assert r_cad["risk"] == ActionRiskLevel.CRITICAL_BLOCKED
    assert r_cad["allowed"] is False
