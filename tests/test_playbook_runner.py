"""Unit tests for PlaybookRunner deterministic macro execution."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from core.app_ast import AppPredicate, AppProfile, AppRecipe, AppState, RecipeStep
from core.playbook_runner import PlaybookRunner
from core.struggle_tracker import StruggleTracker


def test_playbook_runner_successful_execution(tmp_path: Path):
    """Verifies that PlaybookRunner executes steps and handles parameter interpolation."""
    # Mock controller and parser
    mock_controller = MagicMock()
    mock_controller.hotkey.return_value = {"status": "ok"}
    mock_controller.type_text.return_value = {"status": "ok"}

    mock_parser = MagicMock()
    mock_parser.parse_active_window.return_value = {
        "status": "ok",
        "window": "LTspice - [amplifier.asc]",
        "elements": [{"id": 1, "name": "Run/Pause", "type": "Btn"}],
    }

    tracker = StruggleTracker(ledger_path=tmp_path / "friction.json")

    # Define simple recipe
    step1 = RecipeStep(action="hotkey", keys=["ctrl", "o"], wait_ms=0)
    step2 = RecipeStep(action="type_text", text="{path}", press_enter=True, wait_ms=0)
    recipe = AppRecipe(
        recipe_id="open_schematic",
        name="Open Schematic",
        description="Opens schematic",
        parameters=["path"],
        steps=[step1, step2],
    )

    profile = AppProfile(
        app_id="ltspice",
        name="LTspice",
        recipes={"open_schematic": recipe},
    )

    mock_broker = MagicMock()
    mock_broker.find_app_window.return_value = 12345

    runner = PlaybookRunner(
        controller=mock_controller,
        parser=mock_parser,
        tracker=tracker,
        broker=mock_broker,
    )

    res = runner.execute(
        profile=profile,
        recipe_id="open_schematic",
        params={"path": "C:/test/circuit.asc"},
    )

    assert res["status"] == "ok"
    assert res["steps_completed"] == 2
    assert res["total_steps"] == 2
    assert res["pinned_hwnd"] == 12345

    # Verify controller calls pinned to HWND
    mock_controller.hotkey.assert_called_once_with(["ctrl", "o"], target_hwnd=12345)
    mock_controller.type_text.assert_called_once_with("C:/test/circuit.asc", press_enter=True, target_hwnd=12345)


def test_playbook_runner_failure_captures_friction(tmp_path: Path):
    """Verifies that an error in recipe execution captures friction telemetry."""
    mock_controller = MagicMock()
    mock_controller.hotkey.return_value = {"status": "error", "error": "Simulated hardware fault"}

    mock_parser = MagicMock()
    mock_parser.parse_active_window.return_value = {"status": "ok", "window": "TestWindow", "elements": []}

    ledger_path = tmp_path / "friction.json"
    tracker = StruggleTracker(ledger_path=ledger_path)

    step = RecipeStep(action="hotkey", keys=["ctrl", "o"], wait_ms=0)
    recipe = AppRecipe(recipe_id="failing_recipe", name="Fail", description="Fails", steps=[step])
    profile = AppProfile(app_id="testapp", name="TestApp", recipes={"failing_recipe": recipe})

    mock_broker = MagicMock()
    mock_broker.find_app_window.return_value = 12345
    runner = PlaybookRunner(
        controller=mock_controller,
        parser=mock_parser,
        tracker=tracker,
        broker=mock_broker,
    )
    res = runner.execute(profile=profile, recipe_id="failing_recipe")

    assert res["status"] == "error"
    assert "Simulated hardware fault" in res["error"]

    # Verify that struggle tracker logged the failure
    events = tracker.get_events("testapp")
    assert len(events) == 1
    assert "Simulated hardware fault" in events[0].symptom
