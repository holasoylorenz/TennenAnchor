"""
Application State Tree (App-AST) Engine for Windows Desktop Automation.
Models applications as queryable, typed state-action graphs with lightweight predicate matching,
pre-compiled action recipes, and self-refining profile storage.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("desktop_harness.app_ast")

DEFAULT_PROFILES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "apps"


@dataclass
class AppPredicate:
    """Predicate evaluating whether an observed UI matches a specific AppState."""
    title_contains: Optional[str] = None
    title_regex: Optional[str] = None
    has_controls: List[str] = field(default_factory=list)
    min_controls: int = 0
    max_controls: Optional[int] = None

    def evaluate(self, window_name: str, elements: List[Dict[str, Any]]) -> bool:
        if self.title_contains and self.title_contains.lower() not in window_name.lower():
            return False

        if self.title_regex:
            try:
                if not re.search(self.title_regex, window_name, re.IGNORECASE):
                    return False
            except re.error:
                return False

        if len(elements) < self.min_controls:
            return False

        if self.max_controls is not None and len(elements) > self.max_controls:
            return False

        if self.has_controls:
            # Control names in lower case
            element_names = {
                (el.get("name") or "").strip().lower()
                for el in elements
            }
            element_types = {
                (el.get("type") or "").strip().lower()
                for el in elements
            }
            for required in self.has_controls:
                req_lower = required.strip().lower()
                matched = any(req_lower in name for name in element_names) or (req_lower in element_types)
                if not matched:
                    return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and (not isinstance(v, list) or len(v) > 0)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppPredicate:
        return cls(
            title_contains=data.get("title_contains"),
            title_regex=data.get("title_regex"),
            has_controls=data.get("has_controls", []),
            min_controls=data.get("min_controls", 0),
            max_controls=data.get("max_controls"),
        )


@dataclass
class AppState:
    """An identifiable state node in the application's UI hierarchy."""
    state_id: str
    name: str
    description: str
    predicate: AppPredicate
    available_recipes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "name": self.name,
            "description": self.description,
            "predicate": self.predicate.to_dict(),
            "available_recipes": self.available_recipes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppState:
        return cls(
            state_id=data["state_id"],
            name=data.get("name", data["state_id"]),
            description=data.get("description", ""),
            predicate=AppPredicate.from_dict(data.get("predicate", {})),
            available_recipes=data.get("available_recipes", []),
        )


@dataclass
class RecipeStep:
    """A single atomic action within a multi-step macro recipe."""
    action: str  # hotkey, click_control, type_text, press_key, wait_state, sleep
    target: Optional[str] = None  # Control label or selector
    keys: Optional[List[str]] = None
    text: Optional[str] = None
    press_enter: bool = False
    wait_ms: int = 250
    expected_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and (v is not False or k == "press_enter")}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RecipeStep:
        return cls(
            action=data.get("action", "click_control"),
            target=data.get("target"),
            keys=data.get("keys"),
            text=data.get("text"),
            press_enter=data.get("press_enter", False),
            wait_ms=data.get("wait_ms", 250),
            expected_state=data.get("expected_state"),
        )


@dataclass
class AppRecipe:
    """Parameterized composite macro recipe transitioning an application between states."""
    recipe_id: str
    name: str
    description: str
    parameters: List[str] = field(default_factory=list)
    initial_state: Optional[str] = None
    expected_final_state: Optional[str] = None
    steps: List[RecipeStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "initial_state": self.initial_state,
            "expected_final_state": self.expected_final_state,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppRecipe:
        return cls(
            recipe_id=data["recipe_id"],
            name=data.get("name", data["recipe_id"]),
            description=data.get("description", ""),
            parameters=data.get("parameters", []),
            initial_state=data.get("initial_state"),
            expected_final_state=data.get("expected_final_state"),
            steps=[RecipeStep.from_dict(s) for s in data.get("steps", [])],
        )


@dataclass
class AppProfile:
    """Full App-AST definition for an application."""
    app_id: str
    name: str
    executable_patterns: List[str] = field(default_factory=list)
    window_classes: List[str] = field(default_factory=list)
    states: Dict[str, AppState] = field(default_factory=dict)
    recipes: Dict[str, AppRecipe] = field(default_factory=dict)
    domain_hints: Dict[str, Any] = field(default_factory=dict)

    def classify_state(self, window_name: str, elements: List[Dict[str, Any]]) -> Optional[str]:
        """Evaluates predicates to identify current AppState ID."""
        for state_id, state in self.states.items():
            if state.predicate.evaluate(window_name, elements):
                return state_id
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "name": self.name,
            "executable_patterns": self.executable_patterns,
            "window_classes": self.window_classes,
            "states": {k: s.to_dict() for k, s in self.states.items()},
            "recipes": {k: r.to_dict() for k, r in self.recipes.items()},
            "domain_hints": self.domain_hints,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppProfile:
        states = {k: AppState.from_dict(v) for k, v in data.get("states", {}).items()}
        recipes = {k: AppRecipe.from_dict(v) for k, v in data.get("recipes", {}).items()}
        return cls(
            app_id=data["app_id"],
            name=data.get("name", data["app_id"]),
            executable_patterns=data.get("executable_patterns", []),
            window_classes=data.get("window_classes", []),
            states=states,
            recipes=recipes,
            domain_hints=data.get("domain_hints", {}),
        )


class ProfileRegistry:
    """Loads, saves, and discovers AppProfile graphs from storage."""

    def __init__(self, profiles_dir: Optional[Path] = None) -> None:
        self.profiles_dir = profiles_dir or DEFAULT_PROFILES_DIR
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, AppProfile] = {}
        self.reload()

    def reload(self) -> None:
        self._cache.clear()
        for p in self.profiles_dir.glob("*.json"):
            try:
                content = p.read_text(encoding="utf-8")
                data = json.loads(content)
                profile = AppProfile.from_dict(data)
                self._cache[profile.app_id.lower()] = profile
            except Exception as e:
                logger.warning("Failed to load profile from %s: %s", p.name, e)

    def get(self, app_id: str) -> Optional[AppProfile]:
        return self._cache.get(app_id.lower().strip())

    def list_apps(self) -> List[str]:
        return sorted(list(self._cache.keys()))

    def find_for_window(
        self,
        window_name: str,
        elements: List[Dict[str, Any]],
        process_name: Optional[str] = None,
    ) -> Optional[AppProfile]:
        """Matches an active foreground window to a known AppProfile."""
        # Check process name first
        if process_name:
            proc_clean = process_name.lower()
            for profile in self._cache.values():
                for pat in profile.executable_patterns:
                    if pat.lower() in proc_clean:
                        return profile

        # Check window title
        win_clean = window_name.lower()
        for profile in self._cache.values():
            if profile.name.lower() in win_clean or profile.app_id.lower() in win_clean:
                return profile

        # Check state matches
        for profile in self._cache.values():
            if profile.classify_state(window_name, elements) is not None:
                return profile

        return None

    def save(self, profile: AppProfile) -> Path:
        target_file = self.profiles_dir / f"{profile.app_id.lower()}.json"
        content = json.dumps(profile.to_dict(), indent=2)
        target_file.write_text(content, encoding="utf-8")
        self._cache[profile.app_id.lower()] = profile
        logger.info("Saved AppProfile: %s -> %s", profile.app_id, target_file.name)
        return target_file
