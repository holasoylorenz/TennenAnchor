"""
Policy Execution Engine for TennenAnchor.
Executes declarative Behavior Trees with dynamic fallback weighting,
integrates with the persistent friction ledger, and avoids ad-hoc script generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union

from policies.nodes import (
    BehaviorNode,
    ExecutionContext,
    NodeStatus,
)
from core.struggle_tracker import StruggleTracker

logger = logging.getLogger("tennenanchor.policy_engine")

DEFAULT_POLICIES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "policies"


class PolicyEngine:
    """
    Executes declarative Boolean Decision Trees / Behavior Trees for desktop actions.
    Eliminates ad-hoc script writing by maintaining structured, self-healing policy graphs.
    """

    def __init__(
        self,
        policies_dir: Optional[Path] = None,
        tracker: Optional[StruggleTracker] = None,
    ) -> None:
        self.policies_dir = policies_dir or DEFAULT_POLICIES_DIR
        self.policies_dir.mkdir(parents=True, exist_ok=True)
        self.tracker = tracker or StruggleTracker()
        self._cache: Dict[str, Dict[str, Any]] = {}

    def load_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        """Loads policy definition JSON from knowledge/policies/."""
        policy_file = self.policies_dir / f"{policy_id}.json"
        if not policy_file.exists():
            # Try subdirectories or pattern match
            matches = list(self.policies_dir.glob(f"**/{policy_id}.json"))
            if matches:
                policy_file = matches[0]
            else:
                logger.warning("Policy '%s' not found in %s", policy_id, self.policies_dir)
                return None

        try:
            data = json.loads(policy_file.read_text(encoding="utf-8"))
            self._cache[policy_id] = {
                "file_path": policy_file,
                "data": data,
                "tree": BehaviorNode.from_dict(data["tree"]),
            }
            return self._cache[policy_id]
        except Exception as e:
            logger.error("Failed to parse policy '%s': %s", policy_id, e)
            return None

    def save_policy(self, policy_id: str) -> bool:
        """Persists updated weights and telemetry counts back to disk."""
        cached = self._cache.get(policy_id)
        if not cached:
            return False

        try:
            policy_file = cached["file_path"]
            data = cached["data"]
            data["tree"] = cached["tree"].to_dict()
            data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            policy_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception as e:
            logger.error("Failed to save policy '%s': %s", policy_id, e)
            return False

    def list_policies(self) -> List[Dict[str, Any]]:
        """Lists all registered policies."""
        results = []
        for p in self.policies_dir.glob("**/*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append({
                    "policy_id": data.get("policy_id", p.stem),
                    "name": data.get("name", p.stem),
                    "domain": data.get("domain", "generic"),
                    "description": data.get("description", ""),
                    "file": str(p),
                })
            except Exception:
                pass
        return results

    def execute(
        self,
        policy_id: str,
        params: Optional[Dict[str, Any]] = None,
        hwnd: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executes a policy tree against the target application.
        Updates branch weights dynamically and records struggles if all branches fail.
        """
        params = params or {}
        entry = self.load_policy(policy_id)
        if not entry:
            return {
                "status": "error",
                "error": f"Policy '{policy_id}' not found.",
                "available_policies": [p["policy_id"] for p in self.list_policies()],
            }

        tree: BehaviorNode = entry["tree"]
        ctx = ExecutionContext(params=params, hwnd=hwnd)

        t0 = time.perf_counter()
        status = tree.tick(ctx)
        dt_ms = (time.perf_counter() - t0) * 1000

        # Persist updated learned weights back to policy JSON
        self.save_policy(policy_id)

        if status == NodeStatus.SUCCESS:
            return {
                "status": "ok",
                "policy_id": policy_id,
                "execution_time_ms": round(dt_ms, 2),
                "telemetry": ctx.telemetry,
                "params": params,
            }
        else:
            # Record failure in friction ledger
            app_name = entry["data"].get("domain", "desktop")
            self.tracker.record(
                app=app_name,
                action=f"policy_{policy_id}",
                category="POLICY_FAILURE",
                symptom=f"All fallback branches failed for policy '{policy_id}' with params {params}",
                severity="high",
            )
            return {
                "status": "error",
                "policy_id": policy_id,
                "error": f"Policy '{policy_id}' failed all fallback branches.",
                "execution_time_ms": round(dt_ms, 2),
                "telemetry": ctx.telemetry,
            }
