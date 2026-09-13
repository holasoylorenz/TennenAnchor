"""Unit tests for Struggle & Friction Tracker."""

from pathlib import Path
import pytest
from core.struggle_tracker import FrictionEvent, StruggleTracker


def test_struggle_tracker_record_and_deduplication(tmp_path: Path):
    """Verifies that recording friction points increments occurrences on duplicate triggers."""
    ledger_path = tmp_path / "friction_test.json"
    tracker = StruggleTracker(ledger_path=ledger_path)

    # First event
    ev1 = tracker.record(
        app="ltspice",
        action="os.startfile",
        category="UNRESPONSIVE_MECHANISM",
        symptom="Active instance ignored document switch",
        resolution="Used Ctrl+O in-app hotkey",
        refinement="Use Ctrl+O hotkey recipe",
        severity="high",
    )
    assert ev1.occurrences == 1
    assert ev1.app == "ltspice"

    # Exact duplicate event
    ev2 = tracker.record(
        app="ltspice",
        action="os.startfile",
        category="UNRESPONSIVE_MECHANISM",
        symptom="Active instance ignored document switch",
    )
    assert ev2.occurrences == 2
    assert ev2.id == ev1.id

    # Verify reload from disk
    tracker2 = StruggleTracker(ledger_path=ledger_path)
    events = tracker2.get_events("ltspice")
    assert len(events) == 1
    assert events[0].occurrences == 2


def test_struggle_tracker_report_formatting(tmp_path: Path):
    """Verifies formatted report output."""
    ledger_path = tmp_path / "friction_test.json"
    tracker = StruggleTracker(ledger_path=ledger_path)

    tracker.record(
        app="winword",
        action="doc.SaveAs2",
        category="EXECUTION_ERROR",
        symptom="Call was rejected by callee",
        resolution="Check modal state",
        severity="medium",
    )

    report = tracker.format_report("winword")
    assert "STRUGGLE & FRICTION REPORT" in report
    assert "WINWORD" in report
    assert "Call was rejected by callee" in report
