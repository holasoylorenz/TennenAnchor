"""
Interactive Application Lifecycle Broker (ALM) for Windows Desktop Agents.
Handles application discovery, interactive desktop launching via Windows Shell COM,
and splash-screen warm-up synchronization.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from actuation.controller import DesktopController
from core.app_ast import AppProfile
from core.dpi import ensure_interactive_desktop

logger = logging.getLogger("desktop_harness.lifecycle")

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL


class AppLifecycleBroker:
    """
    Manages GUI application lifecycle on Windows.
    Bypasses session isolation and headless spawning traps by using
    Windows Shell COM broker and ctypes-based window discovery.
    """

    def __init__(self, controller: Optional[DesktopController] = None):
        self.controller = controller or DesktopController()
        ensure_interactive_desktop()

    def find_app_window(self, profile: AppProfile) -> Optional[int]:
        """
        Discovers the primary top-level window for an application profile
        using ctypes EnumWindows to avoid pywin32 trampolining issues.
        """
        ensure_interactive_desktop()
        patterns = [p.lower().replace(".exe", "") for p in profile.executable_patterns]
        app_name_lower = profile.name.lower()
        app_id_lower = profile.app_id.lower()

        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]

        candidates_by_title: List[int] = []
        candidates_by_proc: List[int] = []

        def callback(hwnd: int, lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if (rect.right - rect.left) <= 100 or (rect.bottom - rect.top) <= 100:
                return True

            # Check window title
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()

            if app_name_lower in title or app_id_lower in title:
                candidates_by_title.append(hwnd)
                return True

            # Check owning process name
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value > 0:
                try:
                    pname = psutil.Process(pid.value).name().lower()
                    if any(pat in pname for pat in patterns):
                        candidates_by_proc.append(hwnd)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        if candidates_by_title:
            return candidates_by_title[0]
        if candidates_by_proc:
            return candidates_by_proc[0]
        return None

    def resolve_executable_path(self, profile: AppProfile) -> Optional[Path]:
        """Resolves local absolute path to application executable."""
        # 1. Search PATH
        for pat in profile.executable_patterns:
            cmd = shutil.which(pat)
            if cmd:
                return Path(cmd).resolve()

        # 2. Check standard install directories
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

        search_roots = [
            Path(local_appdata) / "Programs",
            Path(local_appdata),
            Path(program_files),
            Path(program_files_x86),
        ]

        for root in search_roots:
            if not root.exists():
                continue
            for pat in profile.executable_patterns:
                # Direct check
                direct = root / pat
                if direct.is_file():
                    return direct
                # Shallow search
                try:
                    for match in root.glob(f"**/{pat}"):
                        if match.is_file():
                            return match.resolve()
                except Exception:
                    pass

        return None

    def ensure_running(self, profile: AppProfile, timeout_sec: float = 12.0) -> int:
        """
        Guarantees that an application is running in the user's interactive desktop.
        Returns the valid top-level window HWND.
        """
        # Step 1: Check if already open
        hwnd = self.find_app_window(profile)
        if hwnd:
            logger.info("Found existing instance for '%s' (HWND: %s)", profile.app_id, hwnd)
            self.controller.force_focus_window(hwnd)
            return hwnd

        logger.info("Application '%s' is not running. Launching via Shell Broker...", profile.app_id)

        # Step 2: Resolve executable path
        exe_path = self.resolve_executable_path(profile)
        launched = False

        if exe_path and exe_path.exists():
            try:
                import win32com.client
                shell = win32com.client.Dispatch("Shell.Application")
                # ShellExecute: file, args, dir, op, show
                args = ""
                if profile.app_id == "ltspice":
                    default_asc = Path(__file__).resolve().parent.parent / "outputs" / "miller_ota.asc"
                    if default_asc.exists():
                        args = str(default_asc.resolve())
                shell.ShellExecute(str(exe_path), args, str(exe_path.parent), "open", 1)
                launched = True
                logger.info("Dispatched ShellExecute for: %s (args: %s)", exe_path, args)
            except Exception as e:
                logger.warning("ShellExecute failed: %s; falling back to Start Menu", e)

        if not launched:
            # Fallback: interactive Start Menu actuation
            logger.info("Launching '%s' via interactive Start Menu sequence...", profile.name)
            self.controller.press_key("win")
            time.sleep(0.4)
            self.controller.type_text(profile.name)
            time.sleep(0.4)
            self.controller.press_key("enter")

        # Step 3: Warm-up watchdog loop
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) < timeout_sec:
            time.sleep(0.5)
            hwnd = self.find_app_window(profile)
            if hwnd:
                logger.info("Application '%s' ready and visible (HWND: %s) after %.1fs",
                            profile.app_id, hwnd, time.perf_counter() - t0)
                self.controller.force_focus_window(hwnd)
                time.sleep(0.3)
                return hwnd

        raise TimeoutError(f"Application '{profile.app_id}' did not create a visible top-level window within {timeout_sec}s.")
