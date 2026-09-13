"""
Buffer Synchronization Manager for Desktop Computer-Use Agents.
Tracks persistent on-disk documents vs. in-memory GUI working buffers,
detects stale application tabs, and computes buffer invalidation reload plans.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("desktop_harness.buffer_sync")
user32 = ctypes.windll.user32


class BufferSyncManager:
    """
    Manages synchronization between disk files and GUI in-memory working buffers.
    Prevents silent bugs where an application ignores on-disk changes because
    the document tab is already open in memory.
    """

    def __init__(self):
        self._tracked_documents: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def compute_file_hash(file_path: Path | str) -> str:
        """Computes rapid SHA256 hash of a file on disk."""
        p = Path(file_path)
        if not p.exists():
            return ""
        data = p.read_bytes()
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def get_window_title(hwnd: int) -> str:
        """Retrieves title of specified HWND."""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def is_document_active_in_window(self, hwnd: int, file_path: Path | str) -> bool:
        """
        Checks whether the specified document filename is actively displayed
        in the application's window title or caption.
        """
        if not hwnd or hwnd <= 0:
            return False
        title = self.get_window_title(hwnd).lower()
        fname = Path(file_path).name.lower()
        stem = Path(file_path).stem.lower()
        return fname in title or f"[{fname}]" in title or f"[{stem}]" in title

    def plan_reload_strategy(
        self,
        hwnd: Optional[int],
        file_path: Path | str,
        app_id: str = "generic",
    ) -> Dict[str, Any]:
        """
        Determines the optimal reload strategy for an application.
        If the file is already open in the GUI and was modified on disk,
        plans a buffer invalidation step (e.g. Ctrl+W) before re-opening.
        """
        p = Path(file_path).resolve()
        current_hash = self.compute_file_hash(p)
        doc_key = str(p).lower()

        last_known = self._tracked_documents.get(doc_key, {})
        last_hash = last_known.get("hash")

        is_active = self.is_document_active_in_window(hwnd, p) if hwnd else False
        is_dirty_on_disk = (last_hash is not None and last_hash != current_hash)

        if is_active:
            logger.info("Document '%s' is actively open in HWND %s (Dirty on disk: %s)",
                        p.name, hwnd, is_dirty_on_disk)
            return {
                "strategy": "discard_buffer_then_open",
                "reason": f"Document '{p.name}' is already open in an active tab; must discard in-memory buffer first.",
                "requires_close_hotkey": ["ctrl", "w"],
                "file_path": str(p),
                "file_hash": current_hash,
                "is_active": True,
            }
        else:
            return {
                "strategy": "direct_open",
                "reason": f"Document '{p.name}' is not currently active; direct open is safe.",
                "requires_close_hotkey": None,
                "file_path": str(p),
                "file_hash": current_hash,
                "is_active": False,
            }

    def record_document_loaded(self, file_path: Path | str, hwnd: Optional[int] = None) -> None:
        """Records that a document has been cleanly synchronized and loaded into the application."""
        p = Path(file_path).resolve()
        h = self.compute_file_hash(p)
        doc_key = str(p).lower()
        self._tracked_documents[doc_key] = {
            "path": str(p),
            "hash": h,
            "mtime": p.stat().st_mtime if p.exists() else 0,
            "hwnd": hwnd,
        }
        logger.info("Tracked document revision for '%s' (hash: %s...)", p.name, h[:8] if h else "none")
