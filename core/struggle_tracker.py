"""
Struggle & Friction Ledger for Windows Desktop Automation.
Tracks operational bottlenecks, unexpected UI states, API failures, and verified resolutions
to drive continuous agent self-refinement and automated playbook optimization.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import re

logger = logging.getLogger("desktop_harness.struggle_tracker")

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "friction_ledger.json"


def sanitize_privacy_text(text: Optional[str]) -> Optional[str]:
    """Strips local Windows user directories and usernames to guarantee zero privacy leakage."""
    if not text:
        return text
    # Replace Windows user profile paths like C:\Users\<name> with ~
    cleaned = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\/]+", "~", text, flags=re.IGNORECASE)
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if user and len(user) > 1:
        cleaned = cleaned.replace(user, "<user>")
    return cleaned


@dataclass
class FrictionEvent:
    id: str
    app: str
    action: str
    category: str  # EXECUTION_ERROR, STATE_MISMATCH, UNRESPONSIVE_MECHANISM, AGENT_FRICTION
    symptom: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    severity: str = "medium"  # low, medium, high, critical
    resolution: Optional[str] = None
    refinement: Optional[str] = None
    occurrences: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FrictionEvent:
        return cls(
            id=data["id"],
            app=data.get("app", "generic"),
            action=data.get("action", ""),
            category=data.get("category", "EXECUTION_ERROR"),
            symptom=data.get("symptom", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            severity=data.get("severity", "medium"),
            resolution=data.get("resolution"),
            refinement=data.get("refinement"),
            occurrences=data.get("occurrences", 1),
        )


class StruggleTracker:
    """Thread-safe persistent ledger tracking friction points during desktop automation."""

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self.ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_ledger_file()

    def _ensure_ledger_file(self) -> None:
        if not self.ledger_path.exists():
            initial_data = {"version": "1.0", "events": []}
            self.ledger_path.write_text(json.dumps(initial_data, indent=2), encoding="utf-8")

    def _load_events_unlocked(self) -> List[FrictionEvent]:
        try:
            content = self.ledger_path.read_text(encoding="utf-8")
            raw = json.loads(content)
            return [FrictionEvent.from_dict(e) for e in raw.get("events", [])]
        except Exception as e:
            logger.warning("Failed to load friction ledger: %s", e)
            return []

    def _save_events_unlocked(self, events: List[FrictionEvent]) -> None:
        payload = {
            "version": "1.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "events": [e.to_dict() for e in events],
        }
        temp_path = self.ledger_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.ledger_path)

    def record(
        self,
        app: str,
        action: str,
        category: str,
        symptom: str,
        resolution: Optional[str] = None,
        refinement: Optional[str] = None,
        severity: str = "medium",
    ) -> FrictionEvent:
        """Records a friction event. If a matching event already exists for app+action+symptom, increments occurrences."""
        app_norm = app.lower().strip()
        action_clean = sanitize_privacy_text(action) or ""
        symptom_clean = sanitize_privacy_text(symptom) or ""
        resolution_clean = sanitize_privacy_text(resolution)
        refinement_clean = sanitize_privacy_text(refinement)

        with self._lock:
            events = self._load_events_unlocked()

            # Deduplication: look for existing match
            for e in events:
                if (
                    e.app.lower() == app_norm
                    and e.action.strip().lower() == action_clean.strip().lower()
                    and e.symptom.strip().lower() == symptom_clean.strip().lower()
                ):
                    e.occurrences += 1
                    e.timestamp = datetime.now(timezone.utc).isoformat()
                    if resolution_clean and not e.resolution:
                        e.resolution = resolution_clean
                    if refinement_clean and not e.refinement:
                        e.refinement = refinement_clean
                    self._save_events_unlocked(events)
                    return e

            # Generate new event ID
            event_id = f"fric_{app_norm}_{len(events) + 1:03d}"
            new_event = FrictionEvent(
                id=event_id,
                app=app_norm,
                action=action_clean,
                category=category,
                symptom=symptom_clean,
                severity=severity,
                resolution=resolution_clean,
                refinement=refinement_clean,
            )
            events.append(new_event)
            self._save_events_unlocked(events)
            logger.info("Recorded new friction event: %s (%s: %s)", event_id, app, action_clean)
            return new_event

    def get_events(self, app: Optional[str] = None) -> List[FrictionEvent]:
        """Returns all events, optionally filtered by application."""
        with self._lock:
            events = self._load_events_unlocked()
            if app:
                target = app.lower().strip()
                return [e for e in events if e.app.lower() == target]
            return events

    def format_report(self, app: Optional[str] = None) -> str:
        """Formats an actionable ASCII summary of struggles and refinement recommendations."""
        events = self.get_events(app)
        if not events:
            filter_str = f" for '{app}'" if app else ""
            return f"No friction events recorded{filter_str}. Execution history is clean."

        lines = [
            "=" * 78,
            f"STRUGGLE & FRICTION REPORT" + (f" - TARGET: {app.upper()}" if app else ""),
            f"Total Bottlenecks Logged: {len(events)}",
            "=" * 78,
        ]

        # Sort by occurrences desc, then severity
        severity_weight = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        sorted_events = sorted(
            events,
            key=lambda e: (severity_weight.get(e.severity, 1), e.occurrences),
            reverse=True,
        )

        for idx, e in enumerate(sorted_events, 1):
            res_str = e.resolution or "Unresolved (workaround needed)"
            ref_str = e.refinement or "No refinement rule specified"
            lines.extend([
                f"\n[{idx}] {e.id.upper()} | App: {e.app} | Severity: {e.severity.upper()} | Hits: {e.occurrences}",
                f"    Action Attempted : {e.action}",
                f"    Category         : {e.category}",
                f"    Symptom / Failure: {e.symptom}",
                f"    Resolution Found : {res_str}",
                f"    Refinement Tip   : {ref_str}",
            ])

        lines.append("\n" + "=" * 78)
        return "\n".join(lines)
