"""Unit tests for Application State Tree (App-AST) engine and ProfileRegistry."""

import json
from pathlib import Path
import pytest
from core.app_ast import AppPredicate, AppProfile, AppRecipe, AppState, ProfileRegistry, RecipeStep


def test_app_predicate_evaluation():
    """Verifies predicate evaluation over title and control sets."""
    pred = AppPredicate(
        title_contains="LTspice",
        has_controls=["Run/Pause", "Wire"],
        min_controls=2,
    )

    # Positive match
    elements = [
        {"id": 1, "name": "Run/Pause", "type": "Btn"},
        {"id": 2, "name": "Wire", "type": "Btn"},
        {"id": 3, "name": "Resistor", "type": "Btn"},
    ]
    assert pred.evaluate("LTspice - [circuit.asc]", elements) is True

    # Title mismatch
    assert pred.evaluate("Calculator", elements) is False

    # Missing required control
    elements_missing = [{"id": 1, "name": "Run/Pause", "type": "Btn"}]
    assert pred.evaluate("LTspice - [circuit.asc]", elements_missing) is False


def test_app_profile_serialization_roundtrip(tmp_path: Path):
    """Verifies that an AppProfile serializes to JSON and deserializes identically."""
    pred = AppPredicate(title_contains="LTspice", has_controls=["Open"])
    state = AppState(
        state_id="idle",
        name="Idle Workspace",
        description="Empty workspace",
        predicate=pred,
        available_recipes=["open_file"],
    )
    step = RecipeStep(action="hotkey", keys=["ctrl", "o"], wait_ms=300)
    recipe = AppRecipe(
        recipe_id="open_file",
        name="Open File",
        description="Opens a file",
        parameters=["path"],
        steps=[step],
    )
    profile = AppProfile(
        app_id="testapp",
        name="Test Application",
        executable_patterns=["test.exe"],
        states={"idle": state},
        recipes={"open_file": recipe},
        domain_hints={"version": 1},
    )

    data = profile.to_dict()
    assert data["app_id"] == "testapp"
    assert "idle" in data["states"]
    assert "open_file" in data["recipes"]

    # Reconstitute
    reconstituted = AppProfile.from_dict(data)
    assert reconstituted.app_id == "testapp"
    assert reconstituted.states["idle"].name == "Idle Workspace"
    assert reconstituted.recipes["open_file"].steps[0].keys == ["ctrl", "o"]


def test_profile_registry_discovery():
    """Verifies that ProfileRegistry discovers pre-seeded apps like ltspice and winword."""
    registry = ProfileRegistry()
    apps = registry.list_apps()
    assert "ltspice" in apps
    assert "winword" in apps

    ltspice = registry.get("ltspice")
    assert ltspice is not None
    assert "empty_workspace" in ltspice.states
    assert "open_schematic" in ltspice.recipes
