"""
Dual-Channel Observer for Desktop Computer-Use Agents.
Unifies Channel A (UI Accessibility Controls & Visuals) with
Channel B (Domain Artifact Extraction: Logs, Waveforms, CSVs, Metrics).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from perception.edge_parser import EdgeUIAParser
from perception.screenshot_escalator import ScreenshotEscalator

logger = logging.getLogger("desktop_harness.dual_observer")


class DualChannelObserver:
    """
    Observes both the graphical user interface and local output artifacts.
    Enables closed-loop verification where an agent asserts not just
    'button was clicked', but 'simulation produced valid metric'.
    """

    def __init__(
        self,
        parser: Optional[EdgeUIAParser] = None,
        escalator: Optional[ScreenshotEscalator] = None,
    ):
        self.parser = parser or EdgeUIAParser()
        self.escalator = escalator or ScreenshotEscalator()

    def observe_ui(self, query: Optional[str] = None) -> Dict[str, Any]:
        """Channel A: Fast Tier 1 UIA crawl of the active foreground window."""
        res = self.parser.parse_active_window(query=query)
        if res.get("status") == "escalate":
            logger.info("Tier 1 recommends escalation; capturing Tier 2 visual fallback...")
            esc_res = self.escalator.capture(target="active_window")
            return {
                "tier": 2,
                "status": esc_res.get("status", "ok"),
                "window": res.get("window", "Unknown"),
                "hwnd": res.get("hwnd"),
                "image_path": esc_res.get("image_path"),
                "scaled_size": esc_res.get("scaled_size"),
                "elements": [],
            }
        return {
            "tier": 1,
            "status": "ok",
            "window": res.get("window", ""),
            "hwnd": res.get("hwnd"),
            "elements": res.get("elements", []),
            "summary_text": self.parser.format_compact_text(res),
        }

    def observe_artifact(
        self,
        file_path: Path | str,
        extract_patterns: Optional[Dict[str, str]] = None,
        tail_lines: int = 50,
    ) -> Dict[str, Any]:
        """
        Channel B: Reads and parses ground-truth output artifacts on disk.
        Applies regex extractors to parse numerical metrics and status flags.
        """
        p = Path(file_path).resolve()
        if not p.exists():
            return {
                "status": "missing",
                "path": str(p),
                "metrics": {},
                "tail": "",
            }

        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return {
                "status": "read_error",
                "path": str(p),
                "error": str(e),
                "metrics": {},
            }

        extracted: Dict[str, Any] = {}
        if extract_patterns:
            for key, pattern in extract_patterns.items():
                m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if m:
                    val_str = m.group(1).strip()
                    try:
                        # Attempt float conversion
                        extracted[key] = float(val_str)
                    except ValueError:
                        extracted[key] = val_str

        lines = content.splitlines()
        tail = "\n".join(lines[-tail_lines:]) if lines else ""

        return {
            "status": "ok",
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "metrics": extracted,
            "tail": tail,
        }

    def observe_closed_loop(
        self,
        ui_query: Optional[str] = None,
        artifact_path: Optional[Path | str] = None,
        extract_patterns: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a dual-channel observation combining UI state and domain artifact data.
        Returns a single unified payload to the agent.
        """
        ui_obs = self.observe_ui(query=ui_query)
        artifact_obs = {}

        if artifact_path:
            artifact_obs = self.observe_artifact(
                file_path=artifact_path,
                extract_patterns=extract_patterns,
            )

        return {
            "status": "ok",
            "ui": ui_obs,
            "artifact": artifact_obs,
        }
