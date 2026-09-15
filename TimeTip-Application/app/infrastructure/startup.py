"""Windows startup registration for the current user."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_NAME = "TimeTip"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class StartupError(RuntimeError):
    """Raised when the operating system cannot update the startup entry."""


def startup_command() -> str:
    """Return the command Windows should run when the user signs in."""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([str(Path(sys.executable).resolve())])
    entrypoint = Path(__file__).resolve().parents[2] / "timetip.py"
    return subprocess.list2cmdline([sys.executable, str(entrypoint)])


def is_startup_enabled() -> bool:
    """Check whether TimeTip has a current-user startup entry."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(str(value).strip())
    except (FileNotFoundError, OSError, ImportError):
        return False


def set_startup_enabled(enabled: bool) -> None:
    """Create or remove the current-user startup entry."""
    if sys.platform != "win32":
        raise StartupError("开机自启仅支持 Windows。")
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except (FileNotFoundError, OSError, ImportError) as error:
        raise StartupError(f"无法更新开机自启设置：{error}") from error
