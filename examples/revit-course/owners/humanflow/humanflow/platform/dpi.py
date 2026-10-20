"""
Windows DPI awareness so mouse coordinates match between recording and playback.

On Windows 10+ with display scaling (125%, 150%, etc.), pynput's Listener and
Controller can use different coordinate systems unless the process is DPI-aware.
That causes recorded (x,y) to be "off by a lot" on playback. Setting DPI awareness
at process start fixes it so both record and play use the same (physical) coords.

See: https://github.com/moses-palmer/pynput/issues/153
"""
from __future__ import annotations

import sys

_dpi_aware_done = False


def ensure_dpi_aware() -> None:
    """
    Make this process use a consistent mouse coordinate system on Windows.
    Safe to call multiple times. No-op on non-Windows.
    Call before any pynput mouse listener or controller is used (e.g. at the
    start of record_clicks and play_clicks_human).
    """
    global _dpi_aware_done
    if _dpi_aware_done:
        return
    _dpi_aware_done = True

    if sys.platform != "win32":
        return

    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 10 1703+)
        # Makes GetCursorPos / SetCursorPos use physical pixels consistently.
        ctypes = __import__("ctypes")
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        try:
            # Fallback for older Windows: legacy DPI aware
            ctypes = __import__("ctypes")
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
