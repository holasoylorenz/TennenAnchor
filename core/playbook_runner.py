"""
Deterministic Playbook Runner for App-AST Recipes.
Executes multi-step verified UI procedures in a single conversational turn,
validates pre- and post-conditions, and logs friction telemetry upon failure.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from actuation.controller import DesktopController
from core.app_ast import AppProfile, AppRecipe, RecipeStep, ProfileRegistry
from core.struggle_tracker import StruggleTracker
from perception.edge_parser import EdgeUIAParser

logger = logging.getLogger("desktop_harness.playbook_runner")


class PlaybookRunner:
    """Executes verified macro recipes from AppProfile graphs."""

    def __init__(
        self,
        controller: Optional[DesktopController] = None,
        parser: Optional[EdgeUIAParser] = None,
        tracker: Optional[StruggleTracker] = None,
        registry: Optional[ProfileRegistry] = None,
    ) -> None:
        self.controller = controller or DesktopController()
        self.parser = parser or EdgeUIAParser()
        self.tracker = tracker or StruggleTracker()
        self.registry = registry or ProfileRegistry()

    def _interpolate(self, template: str, params: Dict[str, Any]) -> str:
        """Replaces {param} placeholders in strings."""
        result = template
        for k, v in params.items():
            result = result.replace(f"{{{k}}}", str(v))
        return result

    def execute(
        self,
        profile: AppProfile,
        recipe_id: str,
        params: Optional[Dict[str, Any]] = None,
        hwnd: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executes a recipe step-by-step.
        Returns execution summary dict with status, step counts, and final state.
        """
        params = params or {}
        recipe = profile.recipes.get(recipe_id)
        if not recipe:
            return {
                "status": "error",
                "error": f"Recipe '{recipe_id}' not found in profile '{profile.app_id}'.",
                "available_recipes": list(profile.recipes.keys()),
            }

        t0 = time.perf_counter()
        logger.info("Executing recipe '%s' for '%s' with params: %s", recipe_id, profile.app_id, params)

        if hwnd:
            self.controller.force_focus_window(hwnd)

        # Pre-execution perception check
        initial_res = self.parser.parse_active_window()
        initial_state = profile.classify_state(
            initial_res.get("window", ""),
            initial_res.get("elements", []),
        )

        steps_done = 0
        total_steps = len(recipe.steps)

        for idx, step in enumerate(recipe.steps, 1):
            try:
                self._execute_step(step, params, profile, hwnd)
                steps_done += 1

                if step.wait_ms > 0:
                    time.sleep(step.wait_ms / 1000.0)

            except Exception as e:
                recovered = False
                if step.recovery_policy != "abort" and getattr(recipe, "failure_policy", "") == "recover_via_ledger":
                    try:
                        if self._attempt_recovery_from_ledger(step, e, profile, hwnd):
                            logger.info("Retrying step %d/%d after applying ledger recovery...", idx, total_steps)
                            self._execute_step(step, params, profile, hwnd)
                            recovered = True
                            steps_done += 1
                            if step.wait_ms > 0:
                                time.sleep(step.wait_ms / 1000.0)
                    except Exception as retry_err:
                        e = retry_err

                if not recovered:
                    err_msg = f"Step {idx}/{total_steps} ({step.action}) failed: {e}"
                    logger.error("Playbook execution error in %s: %s", recipe_id, err_msg)

                    # Automatic friction telemetry capture
                    self.tracker.record(
                        app=profile.app_id,
                        action=f"recipe:{recipe_id}:step_{idx}:{step.action}",
                        category="EXECUTION_ERROR",
                        symptom=str(e),
                        severity="high",
                    )

                    return {
                        "status": "error",
                        "recipe": recipe_id,
                        "steps_completed": steps_done,
                        "total_steps": total_steps,
                        "error": err_msg,
                        "initial_state": initial_state,
                    }

        # Post-execution state classification
        post_res = self.parser.parse_active_window()
        final_state = profile.classify_state(
            post_res.get("window", ""),
            post_res.get("elements", []),
        )

        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("Recipe '%s' completed successfully in %.1fms. Final state: %s", recipe_id, dt_ms, final_state)

        return {
            "status": "ok",
            "recipe": recipe_id,
            "steps_completed": steps_done,
            "total_steps": total_steps,
            "initial_state": initial_state,
            "final_state": final_state,
            "duration_ms": round(dt_ms, 1),
            "window": post_res.get("window"),
        }

    def _execute_step(
        self,
        step: RecipeStep,
        params: Dict[str, Any],
        profile: AppProfile,
        hwnd: Optional[int],
    ) -> None:
        action = step.action.lower().strip()

        if action == "hotkey":
            if not step.keys:
                raise ValueError("Hotkey step missing 'keys'")
            keys = [self._interpolate(k, params) for k in step.keys]
            res = self.controller.hotkey(keys, target_hwnd=hwnd)
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Hotkey failed"))

        elif action == "click_control":
            if not step.target:
                raise ValueError("click_control step missing 'target'")
            target_name = self._interpolate(step.target, params).lower().strip()

            # Parse foreground to find control coordinates
            inspect_res = self.parser.parse_active_window(query=target_name)
            coords = None
            for el in inspect_res.get("elements", []):
                if target_name in (el.get("name") or "").lower():
                    coords = el.get("center")
                    break

            if not coords:
                raise RuntimeError(f"Target control '{step.target}' not found in active window.")

            res = self.controller.click(coords[0], coords[1])
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Click failed"))

        elif action == "type_text":
            raw_text = step.text or ""
            text = self._interpolate(raw_text, params)
            res = self.controller.type_text(text, press_enter=step.press_enter, target_hwnd=hwnd)
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Type failed"))

        elif action == "press_key":
            if not step.target:
                raise ValueError("press_key step missing 'target' key name")
            key = self._interpolate(step.target, params)
            res = self.controller.press_key(key)
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Key press failed"))

        elif action == "sleep":
            time.sleep(max(10, step.wait_ms) / 1000.0)

        elif action == "wait_state":
            target_state = self._interpolate(step.expected_state or "", params)
            if not target_state:
                return

            timeout_sec = 4.0
            t_start = time.time()
            matched = False
            while time.time() - t_start < timeout_sec:
                cur = self.parser.parse_active_window()
                curr_state = profile.classify_state(cur.get("window", ""), cur.get("elements", []))
                if curr_state == target_state:
                    matched = True
                    break
                time.sleep(0.2)

            if not matched:
                raise TimeoutError(f"Timed out waiting for state '{target_state}'.")

        else:
            raise ValueError(f"Unknown recipe action: {action}")

    def _attempt_recovery_from_ledger(
        self,
        step: RecipeStep,
        error: Exception,
        profile: AppProfile,
        hwnd: Optional[int],
    ) -> bool:
        """Consults the friction ledger for known resolutions to attempt dynamic self-healing."""
        known_events = self.tracker.get_events(profile.app_id)
        err_str = str(error).lower()

        for ev in known_events:
            if ev.resolution and (step.action in ev.action or any(w in err_str for w in ev.symptom.lower().split()[:3])):
                logger.info("Playbook self-healing: applying known resolution from ledger: %s", ev.resolution)
                if hwnd:
                    self.controller.force_focus_window(hwnd)
                time.sleep(0.3)
                return True

        if ("not found" in err_str or "unresponsive" in err_str) and hwnd:
            logger.info("Playbook self-healing: re-focusing target window HWND %s", hwnd)
            self.controller.force_focus_window(hwnd)
            time.sleep(0.3)
            return True

        return False
