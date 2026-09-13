"""Unit tests for AppLifecycleBroker."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.app_ast import AppProfile
from core.lifecycle import AppLifecycleBroker


def test_lifecycle_broker_resolves_executable_via_which(tmp_path: Path):
    """Verifies that resolve_executable_path locates binaries via shutil.which."""
    broker = AppLifecycleBroker(controller=MagicMock())
    profile = AppProfile(
        app_id="testapp",
        name="TestApp",
        executable_patterns=["python.exe", "python"],
    )

    resolved = broker.resolve_executable_path(profile)
    assert resolved is not None
    assert resolved.exists()
    assert "python" in resolved.name.lower()


def test_lifecycle_broker_resolves_nonexistent_returns_none():
    """Verifies that an unknown binary gracefully returns None."""
    broker = AppLifecycleBroker(controller=MagicMock())
    profile = AppProfile(
        app_id="nonexistent_tool_xyz",
        name="NonExistentToolXYZ",
        executable_patterns=["nonexistent_tool_xyz_99999.exe"],
    )

    resolved = broker.resolve_executable_path(profile)
    assert resolved is None


def test_lifecycle_broker_find_app_window_existing():
    """Verifies find_app_window finds window when EnumWindows matches title."""
    broker = AppLifecycleBroker(controller=MagicMock())
    profile = AppProfile(
        app_id="ltspice",
        name="LTspice",
        executable_patterns=["XVIIx64.exe", "LTspice.exe"],
    )

    with patch("core.lifecycle.user32") as mock_user32:
        mock_user32.IsWindowVisible.return_value = 1
        mock_user32.GetWindowTextLengthW.return_value = 28

        def mock_get_text(hwnd, buf, maxlen):
            buf.value = "LTspice XVII - [circuit.asc]"
            return len(buf.value)

        def mock_get_rect(hwnd, rect_ref):
            rect_ref._obj.left = 0
            rect_ref._obj.top = 0
            rect_ref._obj.right = 800
            rect_ref._obj.bottom = 600
            return 1

        mock_user32.GetWindowTextW.side_effect = mock_get_text
        mock_user32.GetWindowRect.side_effect = mock_get_rect

        def mock_enum(callback, lparam):
            callback(999, lparam)
            return 1

        mock_user32.EnumWindows.side_effect = mock_enum

        hwnd = broker.find_app_window(profile)
        assert hwnd == 999


def test_ensure_running_returns_existing_hwnd():
    """Verifies ensure_running returns immediately if window already exists."""
    mock_ctrl = MagicMock()
    broker = AppLifecycleBroker(controller=mock_ctrl)
    profile = AppProfile(app_id="testapp", name="TestApp")

    with patch.object(broker, "find_app_window", return_value=54321):
        hwnd = broker.ensure_running(profile)
        assert hwnd == 54321
        mock_ctrl.force_focus_window.assert_called_once_with(54321)
