"""Unit tests for BufferSyncManager."""

from pathlib import Path
from unittest.mock import patch
import pytest

from core.buffer_sync import BufferSyncManager


def test_compute_file_hash(tmp_path: Path):
    """Verifies file hash calculation and missing file handling."""
    sync = BufferSyncManager()

    # Nonexistent file
    assert sync.compute_file_hash(tmp_path / "missing.txt") == ""

    # Existing file
    test_file = tmp_path / "doc.asc"
    test_file.write_text("Version 4\nSHEET 1 880 680\n", encoding="utf-8")
    h1 = sync.compute_file_hash(test_file)
    assert len(h1) == 64  # sha256 hex length

    # Mutated file produces distinct hash
    test_file.write_text("Version 4\nSHEET 1 880 680\nWIRE 0 0\n", encoding="utf-8")
    h2 = sync.compute_file_hash(test_file)
    assert h2 != h1


def test_is_document_active_in_window():
    """Verifies detection of active document name in window title."""
    sync = BufferSyncManager()

    with patch.object(sync, "get_window_title", return_value="LTspice XVII - [miller_ota.asc]"):
        assert sync.is_document_active_in_window(12345, "C:/circuits/miller_ota.asc") is True
        assert sync.is_document_active_in_window(12345, "C:/circuits/buck_boost.asc") is False

    with patch.object(sync, "get_window_title", return_value="Untitled - Notepad"):
        assert sync.is_document_active_in_window(12345, "C:/test/file.txt") is False

    # Invalid HWND
    assert sync.is_document_active_in_window(0, "C:/test/file.txt") is False


def test_plan_reload_strategy_direct_open(tmp_path: Path):
    """Verifies direct_open strategy when document is not open in the window."""
    sync = BufferSyncManager()
    doc = tmp_path / "test.asc"
    doc.write_text("Test content", encoding="utf-8")

    with patch.object(sync, "is_document_active_in_window", return_value=False):
        plan = sync.plan_reload_strategy(123, doc, "ltspice")
        assert plan["strategy"] == "direct_open"
        assert plan["requires_close_hotkey"] is None
        assert plan["is_active"] is False


def test_plan_reload_strategy_discard_buffer(tmp_path: Path):
    """Verifies discard_buffer_then_open strategy when document is already active in window."""
    sync = BufferSyncManager()
    doc = tmp_path / "test.asc"
    doc.write_text("Test content", encoding="utf-8")

    with patch.object(sync, "is_document_active_in_window", return_value=True):
        plan = sync.plan_reload_strategy(123, doc, "ltspice")
        assert plan["strategy"] == "discard_buffer_then_open"
        assert plan["requires_close_hotkey"] == ["ctrl", "w"]
        assert plan["is_active"] is True


def test_record_document_loaded(tmp_path: Path):
    """Verifies tracking of loaded document revisions."""
    sync = BufferSyncManager()
    doc = tmp_path / "test.asc"
    doc.write_text("Initial", encoding="utf-8")

    sync.record_document_loaded(doc, hwnd=777)
    key = str(doc.resolve()).lower()
    assert key in sync._tracked_documents
    assert sync._tracked_documents[key]["hwnd"] == 777
    assert len(sync._tracked_documents[key]["hash"]) == 64
