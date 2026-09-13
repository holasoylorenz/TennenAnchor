"""Unit tests for DualChannelObserver."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from core.dual_observer import DualChannelObserver


def test_dual_observer_observe_ui_tier1():
    """Verifies Channel A observation when Tier 1 UIA succeeds."""
    mock_parser = MagicMock()
    mock_parser.parse_active_window.return_value = {
        "status": "ok",
        "window": "LTspice XVII",
        "hwnd": 12345,
        "elements": [{"id": 1, "name": "Run"}],
    }
    mock_parser.format_compact_text.return_value = "[1] 'Run' (Button)"

    obs = DualChannelObserver(parser=mock_parser)
    res = obs.observe_ui()

    assert res["tier"] == 1
    assert res["status"] == "ok"
    assert res["window"] == "LTspice XVII"
    assert res["hwnd"] == 12345
    assert len(res["elements"]) == 1
    assert "Run" in res["summary_text"]


def test_dual_observer_observe_ui_tier2_escalation():
    """Verifies Channel A falls back to Tier 2 screenshot when UIA recommends escalation."""
    mock_parser = MagicMock()
    mock_parser.parse_active_window.return_value = {
        "status": "escalate",
        "window": "Legacy App",
        "hwnd": 99999,
        "elements": [],
    }

    mock_escalator = MagicMock()
    mock_escalator.capture.return_value = {
        "status": "ok",
        "image_path": "outputs/screenshots/snap.png",
        "scaled_size": (1280, 720),
    }

    obs = DualChannelObserver(parser=mock_parser, escalator=mock_escalator)
    res = obs.observe_ui()

    assert res["tier"] == 2
    assert res["status"] == "ok"
    assert res["image_path"] == "outputs/screenshots/snap.png"


def test_dual_observer_observe_artifact_missing(tmp_path: Path):
    """Verifies Channel B returns missing status on nonexistent file."""
    obs = DualChannelObserver()
    res = obs.observe_artifact(tmp_path / "nonexistent.log")

    assert res["status"] == "missing"
    assert res["metrics"] == {}


def test_dual_observer_observe_artifact_extraction(tmp_path: Path):
    """Verifies Channel B extracts regex metrics from domain output logs."""
    log_file = tmp_path / "miller_ota.log"
    log_content = (
        "Circuit: * Two-Stage Miller OTA\n"
        "Direct Newton iteration failed to find .op point.\n"
        "Measurement: a0_db\n"
        "  step  gain_db  gain_mag\n"
        "     1  64.352   1650.4\n"
        "Measurement: gbw_hz\n"
        "  step  f_unity\n"
        "     1  1.542e+07\n"
    )
    log_file.write_text(log_content, encoding="utf-8")

    obs = DualChannelObserver()
    patterns = {
        "a0_db": r"Measurement:\s*a0_db.*?1\s+([0-9\.\+\-eE]+)",
        "gbw_hz": r"Measurement:\s*gbw_hz.*?1\s+([0-9\.\+\-eE]+)",
    }

    res = obs.observe_artifact(log_file, extract_patterns=patterns)

    assert res["status"] == "ok"
    assert res["metrics"]["a0_db"] == 64.352
    assert res["metrics"]["gbw_hz"] == 1.542e7
    assert "Two-Stage Miller OTA" in res["tail"]


def test_dual_observer_closed_loop(tmp_path: Path):
    """Verifies unified closed-loop observation combining Channel A and Channel B."""
    mock_parser = MagicMock()
    mock_parser.parse_active_window.return_value = {
        "status": "ok",
        "window": "LTspice XVII",
        "hwnd": 12345,
        "elements": [],
    }
    mock_parser.format_compact_text.return_value = "LTspice"

    log_file = tmp_path / "sim.log"
    log_file.write_text("Vout_rms = 4.982 V\n", encoding="utf-8")

    obs = DualChannelObserver(parser=mock_parser)
    res = obs.observe_closed_loop(
        ui_query="LTspice",
        artifact_path=log_file,
        extract_patterns={"vout": r"Vout_rms\s*=\s*([0-9\.]+)"},
    )

    assert res["status"] == "ok"
    assert res["ui"]["status"] == "ok"
    assert res["artifact"]["metrics"]["vout"] == 4.982
