# ui_utils.py
#
# Small shared helpers so every Tk window in the app (main GUI, license
# gate, calibrator, ...) looks and behaves the same way: no native OS
# title bar, opened centered on screen, with a matching custom title
# strip that still supports drag-to-move and an optional "X" to close.

import tkinter as tk


def _screen_size(win):
    win.update_idletasks()
    return win.winfo_screenwidth(), win.winfo_screenheight()


def center_window(win, width, height):
    """Center a Tk/Toplevel window on the screen at a fixed size."""
    win.update_idletasks()
    screen_w, screen_h = _screen_size(win)
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def center_window_auto(win, parent=None):
    """Center a window using its requested size. When *parent* is given,
    center over that window instead of the full screen - borderless
    modals stay visually tied to the main app rather than jumping to
    screen center (which on some Windows builds looked like top-left
    placement when overrideredirect mapped before geometry settled)."""
    win.update_idletasks()
    width = max(win.winfo_reqwidth(), win.winfo_width())
    height = max(win.winfo_reqheight(), win.winfo_height())

    if parent is not None:
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + max(0, (pw - width) // 2)
            y = py + max(0, (ph - height) // 2)
        except tk.TclError:
            parent = None

    if parent is None:
        screen_w, screen_h = _screen_size(win)
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)

    win.geometry(f"{width}x{height}+{x}+{y}")


def finalize_toplevel(win, parent=None):
    """Call once all widgets are packed. Ensures overrideredirect windows
    get a correct size/position after mapping (fixes top-left flash in
    frozen exe builds)."""
    def _place():
        win.update_idletasks()
        center_window_auto(win, parent=parent)
        raise_above(win)

    _place()
    # One more pass after the window manager finishes mapping.
    win.after(10, _place)


def make_borderless(win, width, height):
    """Strip the native OS title bar/border. Does NOT set position - call
    finalize_toplevel() or center_window() after packing content."""
    win.overrideredirect(True)
    win.geometry(f"{width}x{height}")


def raise_above(win):
    """Force a borderless/topmost window to actually land above everything
    else, including other topmost windows (like the main GUI)."""
    win.lift()
    win.attributes("-topmost", True)
    win.after(50, lambda: (win.lift(), win.attributes("-topmost", True)))


def add_title_strip(win, parent, text, bg, panel_bg, fg, fg_dim, close_command=None,
                     font=("Georgia", 10, "bold")):
    """Build a slim custom title strip (drag-to-move + optional close 'X')
    to replace the native title bar that overrideredirect() removed, plus a
    1px divider beneath it - matching the main window's title bar exactly.
    Pack this before any other content so it sits at the very top. Returns
    the strip Frame.
    """
    strip = tk.Frame(parent, bg=panel_bg, bd=0)
    strip.pack(fill="x")

    drag_state = {"x": 0, "y": 0}

    def start_move(event):
        drag_state["x"] = event.x
        drag_state["y"] = event.y

    def do_move(event):
        x = win.winfo_x() - drag_state["x"] + event.x
        y = win.winfo_y() - drag_state["y"] + event.y
        win.geometry(f"+{x}+{y}")

    label = tk.Label(strip, text=text, bg=panel_bg, fg=fg, font=font)
    label.pack(side="left", padx=8, pady=6)
    strip.bind("<ButtonPress-1>", start_move)
    strip.bind("<B1-Motion>", do_move)
    label.bind("<ButtonPress-1>", start_move)
    label.bind("<B1-Motion>", do_move)

    if close_command:
        close_btn = tk.Button(
            strip, text="✕", bg=panel_bg, fg=fg_dim, bd=0,
            activebackground="#C24C4C", activeforeground="#FFFFFF",
            command=close_command, cursor="hand2", font=("Segoe UI", 10)
        )
        close_btn.pack(side="right", padx=8)

    tk.Frame(parent, bg=bg, height=1).pack(fill="x")
