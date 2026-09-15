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
from core.buffer_sync import BufferSyncManager
from core.dual_observer import DualChannelObserver
from core.lifecycle import AppLifecycleBroker
from core.struggle_tracker import StruggleTracker
from perception.edge_parser import EdgeUIAParser

import ctypes
from ctypes import wintypes
user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND

logger = logging.getLogger("tennenanchor.playbook_runner")


class PlaybookRunner:
    """
    TennenAnchor Pinned Transaction Runner.
    Executes verified macro recipes from AppProfile graphs with
    managed lifecycle attachment, buffer synchronization, focus pinning,
    and dual-channel artifact verification.
    """

    def __init__(
        self,
        controller: Optional[DesktopController] = None,
        parser: Optional[EdgeUIAParser] = None,
        tracker: Optional[StruggleTracker] = None,
        registry: Optional[ProfileRegistry] = None,
        broker: Optional[AppLifecycleBroker] = None,
        buffer_sync: Optional[BufferSyncManager] = None,
        dual_observer: Optional[DualChannelObserver] = None,
    ) -> None:
        self.controller = controller or DesktopController()
        self.parser = parser or EdgeUIAParser()
        self.tracker = tracker or StruggleTracker()
        self.registry = registry or ProfileRegistry()
        self.broker = broker or AppLifecycleBroker(controller=self.controller)
        self.buffer_sync = buffer_sync or BufferSyncManager()
        self.dual_observer = dual_observer or DualChannelObserver(parser=self.parser)

    def _interpolate(self, template: str, params: Dict[str, Any]) -> str:
        """Replaces {param} placeholders in strings, normalizing file paths on Windows."""
        import os
        result = template
        for k, v in params.items():
            val_str = str(v)
            if os.name == "nt" and ("/" in val_str or "\\" in val_str or k in ("path", "file")):
                try:
                    val_str = os.path.normpath(val_str)
                except Exception:
                    pass
            result = result.replace(f"{{{k}}}", val_str)
        return result

    def execute(
        self,
        profile: AppProfile,
        recipe_id: str,
        params: Optional[Dict[str, Any]] = None,
        hwnd: Optional[int] = None,
        record: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes a recipe step-by-step as a pinned transaction.
        Returns execution summary dict with status, step counts, final state, and extracted artifacts.
        Optionally records window-scoped animated GIF visual proof if record=True.
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

        # 1. Lifecycle Resolution & Target HWND Pinning
        pinned_hwnd = hwnd
        if not pinned_hwnd:
            pinned_hwnd = self.broker.find_app_window(profile)
            if not pinned_hwnd:
                try:
                    pinned_hwnd = self.broker.ensure_running(profile)
                except Exception as launch_err:
                    logger.warning("Could not auto-ensure running '%s': %s", profile.app_id, launch_err)

        if pinned_hwnd:
            self.controller.force_focus_window(pinned_hwnd)

        # Optional Session Recorder for Visual Proof (Dev Mode)
        recorder = None
        if record:
            from core.recorder import WindowScopedRecorder, is_recorder_available
            if is_recorder_available():
                recorder = WindowScopedRecorder(hwnd=pinned_hwnd)
                recorder.start()
                recorder.set_status(f"Starting {recipe_id}")
            else:
                logger.info("Recording requested but developer dependencies (mss) are not installed. Install with 'pip install -e .[recording]'.")

        # 2. Buffer Synchronization (Disk vs GUI Working Buffer)
        doc_path = params.get("path") or params.get("file")
        if doc_path:
            plan = self.buffer_sync.plan_reload_strategy(pinned_hwnd, doc_path, profile.app_id)
            if plan.get("strategy") == "discard_buffer_then_open" and plan.get("requires_close_hotkey"):
                logger.info("BufferSyncManager: Discarding active in-memory buffer via %s prior to reload", plan["requires_close_hotkey"])
                if recorder:
                    recorder.set_status("BufferSync: Discarding stale in-memory tab")
                self.controller.hotkey(plan["requires_close_hotkey"], target_hwnd=pinned_hwnd)
                time.sleep(0.3)

        # Pre-execution perception check
        initial_res = self.parser.parse_active_window()
        initial_state = profile.classify_state(
            initial_res.get("window", ""),
            initial_res.get("elements", []),
        )

        steps_done = 0
        total_steps = len(recipe.steps)

        for idx, step in enumerate(recipe.steps, 1):
            if recorder:
                recorder.set_status(f"Step {idx}/{total_steps}: {step.action}")

            # Focus Invariant Guard: re-assert focus if background events caused drift
            if pinned_hwnd:
                fg = user32.GetForegroundWindow()
                if fg != pinned_hwnd and not self.controller.is_window_or_descendant(fg, pinned_hwnd):
                    logger.debug("Focus drift detected (FG: %s != Target: %s). Re-asserting focus...", fg, pinned_hwnd)
                    self.controller.force_focus_window(pinned_hwnd)
                    time.sleep(0.08)

            try:
                self._execute_step(step, params, profile, pinned_hwnd)
                steps_done += 1

                if step.wait_ms > 0:
                    time.sleep(step.wait_ms / 1000.0)

            except Exception as e:
                recovered = False
                if step.recovery_policy != "abort" and getattr(recipe, "failure_policy", "") == "recover_via_ledger":
                    try:
                        if self._attempt_recovery_from_ledger(step, e, profile, pinned_hwnd):
                            logger.info("Retrying step %d/%d after applying ledger recovery...", idx, total_steps)
                            if recorder:
                                recorder.set_status(f"Self-Healing: applying ledger recovery for step {idx}")
                            self._execute_step(step, params, profile, pinned_hwnd)
                            recovered = True
                            steps_done += 1
                            if step.wait_ms > 0:
                                time.sleep(step.wait_ms / 1000.0)
                    except Exception as retry_err:
                        e = retry_err

                if not recovered:
                    err_msg = f"Step {idx}/{total_steps} ({step.action}) failed: {e}"
                    logger.error("Playbook execution error in %s: %s", recipe_id, err_msg)

                    if recorder:
                        recorder.set_status(f"Failed at step {idx}: {step.action}")
                        rec_path = recorder.stop(filename_prefix=f"{profile.app_id}_{recipe_id}_failed")

                    # Automatic friction telemetry capture
                    self.tracker.record(
                        app=profile.app_id,
                        action=f"recipe:{recipe_id}:step_{idx}:{step.action}",
                        category="EXECUTION_ERROR",
                        symptom=str(e),
                        severity="high",
                    )

                    err_payload = {
                        "status": "error",
                        "recipe": recipe_id,
                        "steps_completed": steps_done,
                        "total_steps": total_steps,
                        "error": err_msg,
                        "initial_state": initial_state,
                        "pinned_hwnd": pinned_hwnd,
                    }
                    if recorder and rec_path:
                        err_payload["recording_path"] = str(rec_path)
                    return err_payload

        # Record loaded document in buffer sync manager
        if doc_path:
            self.buffer_sync.record_document_loaded(doc_path, pinned_hwnd)

        # Post-execution state classification (Channel A)
        post_res = self.parser.parse_active_window()
        final_state = profile.classify_state(
            post_res.get("window", ""),
            post_res.get("elements", []),
        )

        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("Recipe '%s' completed successfully in %.1fms. Final state: %s", recipe_id, dt_ms, final_state)

        result_payload = {
            "status": "ok",
            "recipe": recipe_id,
            "steps_completed": steps_done,
            "total_steps": total_steps,
            "initial_state": initial_state,
            "final_state": final_state,
            "duration_ms": round(dt_ms, 1),
            "pinned_hwnd": pinned_hwnd,
            "window": post_res.get("window"),
        }

        # Finalize Session Recording if enabled
        if recorder:
            recorder.set_status(f"Verified: {final_state} ({dt_ms:.0f}ms)")
            time.sleep(0.3)
            rec_path = recorder.stop(filename_prefix=f"{profile.app_id}_{recipe_id}")
            if rec_path:
                result_payload["recording_path"] = str(rec_path)

        # Dual-Channel Artifact Extraction (Channel B)
        artifact_spec = getattr(recipe, "artifact_postconditions", None)
        if artifact_spec and isinstance(artifact_spec, dict):
            art_file = self._interpolate(artifact_spec.get("file", ""), params)
            art_patterns = artifact_spec.get("extract_patterns", {})
            if art_file:
                art_obs = self.dual_observer.observe_artifact(art_file, extract_patterns=art_patterns)
                result_payload["artifacts"] = art_obs.get("metrics", {})
                logger.info("Channel B extracted artifact metrics: %s", result_payload["artifacts"])

        return result_payload

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
                el_name = (el.get("name") or "").lower()
                el_type = (el.get("type") or "").lower()
                if target_name in el_name or target_name == el_type:
                    coords = el.get("center")
                    break

            if not coords:
                raise RuntimeError(f"Target control '{step.target}' not found in active window.")

            res = self.controller.click(coords[0], coords[1])
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Click failed"))

        elif action in ("type_text", "type"):
            raw_text = step.text or ""
            text = self._interpolate(raw_text, params)
            res = self.controller.type_text(text, press_enter=step.press_enter, target_hwnd=hwnd)
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Type failed"))

        elif action == "press_key":
            target_key = step.target or getattr(step, "key", None)
            if not target_key:
                raise ValueError("press_key step missing 'target' key name")
            key = self._interpolate(target_key, params)
            res = self.controller.press_key(key)
            if res.get("status") != "ok":
                raise RuntimeError(res.get("error", "Key press failed"))

        elif action == "sleep":
            time.sleep(max(10, step.wait_ms) / 1000.0)

        elif action == "wait_state":
            target_state = self._interpolate(step.expected_state or "", params)
            if not target_state:
                return

            timeout_sec = max(4.0, (step.wait_ms or 0) / 1000.0)
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
