# dpi_utils.py
#
# Windows renders this app through a compatibility scaler unless the process
# explicitly declares itself DPI-aware. Left undeclared, Tkinter and
# pyautogui both see a "virtual" (scaled) resolution that Windows stretches
# back to the real screen - so at anything other than exactly 100% scaling,
# a scan region picked with "Set Scan Region" (which reads pyautogui's
# on-screen mouse position) silently drifts from what a screenshot of that
# same region actually captures. It gets worse on a second monitor running
# a different scale factor than the first, since the mismatch changes
# depending on which screen you're on. This is almost always the real cause
# behind "it worked yesterday, now clicks/detection land in the wrong spot."
#
# Fix: mark the process DPI aware - ideally Per-Monitor-V2 - before ANY
# window is created. Windows locks in a process's DPI-awareness mode the
# first time a window is shown, so this has to run before main.pyw creates
# the license gate window, not just before the main GUI.

import sys


def enable_dpi_awareness():
    """Best-effort: tries the most capable mode first and silently falls
    back on older Windows. No-op on non-Windows platforms. Safe to call
    more than once."""
    if sys.platform != 'win32':
        return

    import ctypes

    try:
        # Windows 10 1703+: per-monitor-v2 - stays correct even if the
        # window is dragged from one monitor to another running a
        # different scale factor.
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ):
            return
    except Exception:
        pass

    try:
        # Windows 8.1+ fallback: per-monitor aware, just not V2 (won't
        # live-rescale mid-drag between monitors, but still fixes
        # coordinate/region accuracy on whichever monitor it started on).
        PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        return
    except Exception:
        pass

    try:
        # Vista/7 fallback: system-DPI aware only, but still far better
        # than the default "unaware" mode pyautogui/tkinter would
        # otherwise inherit.
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
