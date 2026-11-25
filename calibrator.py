# calibrator.py
#
# Two-shot auto-calibration: take a screenshot of the item UNLIT, take one
# LIT, and let the tool figure out both WHERE the glow is and WHAT color it
# is - rather than assuming (like the old border-ring approach did) that the
# indicator is a colored outline touching the edges of the scan region. Some
# items glow that way; plenty don't (an internal highlight, a whole-icon
# brightness change, etc), and border-only detection is blind to those since
# it never even looks at those pixels.
#
# Step 1: diff the two captures pixel-by-pixel and auto-threshold (Otsu) to
# find whichever pixels actually changed - that becomes the "watch zone",
# whatever shape or position it turns out to be.
# Step 2: within just that zone, search HSV tolerances loosest -> tightest
# and keep the loosest one that still keeps the unlit capture out of range.
# Looser bounds survive lighting/monitor drift better, so we prefer loose
# whenever it's safe.
#
# The user can still nudge the result with the slider and watch both test
# results update live, and see the detected zone highlighted on both
# previews. The old full HSV tuner is still reachable via "Advanced" for the
# rare case where even this can't find a clean separation (e.g. the glow is
# a full-screen brightness/particle effect rather than anything local to the
# item, or lit/unlit are just too visually similar).

import threading
import time
import tkinter as tk
from PIL import Image, ImageTk
import cv2
import numpy as np
import pyautogui

import config
import settings_manager
import vision
import ui_utils

# What counts as "found a clean separation" during the auto search.
AUTO_MIN_LIT_MATCH = 60.0     # lit capture must clear this % to count as a solid hit
AUTO_MAX_UNLIT_MATCH = 8.0    # unlit capture must stay under this % to count as a clean miss


class ClickCalibrator:
    DISPLAY_MIN = 200   # upscale each (usually tiny) preview so it's readable side by side

    def __init__(self, parent, on_saved=None, on_advanced=None, on_closed=None):
        self.parent = parent
        self.on_saved = on_saved
        self.on_advanced = on_advanced
        self.on_closed = on_closed

        self.unlit_bgr = None
        self.lit_bgr = None
        self.diff_mask = None
        self._pending_lower = None
        self._pending_upper = None
        self._pending_threshold = None
        self._auto_ran = False

        if not config.SCAN_REGION:
            return

        self.win = tk.Toplevel(parent)
        self.win.configure(bg="#12161C")
        self.win.resizable(False, False)
        self.win.transient(parent)
        # No native OS title bar - matches the main window's look. Size here
        # is dynamic (depends on the packed previews), so it gets centered
        # once all content below is built, at the bottom of __init__.
        self.win.overrideredirect(True)
        # Main window is always-on-top, so this needs to be too or it can
        # render behind it despite having input focus (grab_set).
        self.win.attributes("-topmost", True)
        ui_utils.add_title_strip(
            self.win, self.win, "CALIBRATE - LIT VS UNLIT",
            bg="#12161C", panel_bg="#1C222A", fg="#80DDC0", fg_dim="#A4B1BC",
            close_command=self.win.destroy
        )
        self.win.grab_set()

        self.status_var = tk.StringVar(
            value="Step 1 - make sure the item is UNLIT, then click 'Capture Unlit'"
        )
        tk.Label(
            self.win, textvariable=self.status_var, bg="#12161C", fg="#80DDC0",
            font=("Segoe UI", 10, "bold"), wraplength=420, justify="left"
        ).pack(pady=(12, 6), padx=12, anchor="w")

        previews = tk.Frame(self.win, bg="#12161C")
        previews.pack(padx=12)

        self.unlit_col, self.unlit_canvas, self.unlit_label = self._build_preview_col(
            previews, "UNLIT (idle)", side="left"
        )
        self.lit_col, self.lit_canvas, self.lit_label = self._build_preview_col(
            previews, "LIT (target)", side="left"
        )

        cap_frame = tk.Frame(self.win, bg="#12161C")
        cap_frame.pack(fill="x", padx=12, pady=(8, 4))
        self.capture_unlit_btn = tk.Button(
            cap_frame, text="1. Capture UNLIT", command=self._capture_unlit,
            bg="#29343E", fg="#80DDC0", relief="flat", padx=8, pady=6, cursor="hand2"
        )
        self.capture_unlit_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.capture_lit_btn = tk.Button(
            cap_frame, text="2. Capture LIT", command=self._capture_lit,
            bg="#29343E", fg="#80DDC0", relief="flat", padx=8, pady=6, cursor="hand2"
        )
        self.capture_lit_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))

        result_frame = tk.Frame(self.win, bg="#12161C")
        result_frame.pack(fill="x", padx=12, pady=(4, 0))
        self.result_var = tk.StringVar(value="Capture both to auto-calibrate.")
        tk.Label(
            result_frame, textvariable=self.result_var, bg="#12161C", fg="#F0F4F5",
            font=("Segoe UI", 9), justify="left", wraplength=420
        ).pack(anchor="w")

        slider_frame = tk.Frame(self.win, bg="#12161C")
        slider_frame.pack(fill="x", padx=12, pady=(4, 6))
        tk.Label(
            slider_frame, text="Tolerance (looser = tolerates more lighting variation)",
            bg="#12161C", fg="#F0F4F5", font=("Segoe UI", 8)
        ).pack(anchor="w")
        self.tol_var = tk.IntVar(value=35)
        self.tol_slider = tk.Scale(
            slider_frame, from_=1, to=100, orient="horizontal", variable=self.tol_var,
            command=lambda _e: self._on_tolerance_change(), bg="#12161C", fg="#80DDC0",
            troughcolor="#29343E", highlightthickness=0, activebackground="#AFF6DF",
            state="disabled"
        )
        self.tol_slider.pack(fill="x")

        btn_frame = tk.Frame(self.win, bg="#12161C")
        btn_frame.pack(fill="x", padx=12, pady=(4, 12))
        tk.Button(
            btn_frame, text="Reset Both", command=self._reset,
            bg="#29343E", fg="#A4B1BC", relief="flat", padx=8, pady=6, cursor="hand2"
        ).pack(side="left")
        tk.Button(
            btn_frame, text="Advanced Tuner", command=self._open_advanced,
            bg="#29343E", fg="#A4B1BC", relief="flat", padx=8, pady=6, cursor="hand2"
        ).pack(side="left", padx=6)
        self.save_btn = tk.Button(
            btn_frame, text="Save", command=self._save, state="disabled",
            bg="#29343E", fg="#8FBF6B", relief="flat", padx=8, pady=6, cursor="hand2"
        )
        self.save_btn.pack(side="right")
        tk.Button(
            btn_frame, text="Cancel", command=self.win.destroy,
            bg="#29343E", fg="#C24C4C", relief="flat", padx=8, pady=6, cursor="hand2"
        ).pack(side="right", padx=6)

        self.win.bind("<Destroy>", lambda e: self._on_destroy(), add="+")

        # Content is all packed now, so its requested size is known - center
        # over the main window (borderless dialogs otherwise flash top-left).
        ui_utils.finalize_toplevel(self.win, parent=parent)

    def _on_destroy(self):
        if self.on_closed:
            self.on_closed()

    # --- UI helpers ----------------------------------------------------

    def _build_preview_col(self, parent, title, side):
        col = tk.Frame(parent, bg="#12161C")
        col.pack(side=side, padx=6)
        tk.Label(col, text=title, bg="#12161C", fg="#F0F4F5", font=("Segoe UI", 8, "bold")).pack()
        canvas = tk.Canvas(col, width=self.DISPLAY_MIN, height=self.DISPLAY_MIN,
                            highlightthickness=0, bg="#000000")
        canvas.pack(pady=(2, 2))
        label = tk.Label(col, text="not captured", bg="#12161C", fg="#A4B1BC", font=("Segoe UI", 8))
        label.pack()
        return col, canvas, label

    def _draw_preview(self, canvas, bgr, outline=None, mask=None):
        display = bgr
        if mask is not None:
            # Magenta tint over whatever pixels the diff mask picked out, so
            # the user can see exactly what the tool decided to watch -
            # instead of just trusting a number.
            tint = np.full_like(bgr, (255, 0, 255))
            blended = cv2.addWeighted(bgr, 0.55, tint, 0.45, 0)
            display = bgr.copy()
            display[mask] = blended[mask]

        h, w = display.shape[:2]
        scale = max(1, self.DISPLAY_MIN // max(w, h, 1))
        disp_w, disp_h = w * scale, h * scale
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((disp_w, disp_h), Image.NEAREST)
        tk_img = ImageTk.PhotoImage(img)
        canvas.config(width=disp_w, height=disp_h)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=tk_img)
        if outline:
            canvas.create_rectangle(2, 2, disp_w - 2, disp_h - 2, outline=outline, width=3)
        return tk_img  # caller must keep a reference

    # --- Capture ---------------------------------------------------------
    # Two problems, one shared fix, but only ONE of them needs hiding the
    # window: (1) if this dialog happens to be sitting on top of the scan
    # region on screen, a screenshot taken while it's visible would just
    # capture its own dark UI instead of the game underneath - hiding it
    # avoids that. (2) if the glow is hover-triggered, clicking the capture
    # button moves the mouse off the item and kills the glow before we ever
    # screenshot it - a short countdown gives the user time to get it lit
    # again, which has nothing to do with whether the window is visible.
    # So: always run the countdown, but only withdraw the window first if
    # it's actually overlapping the region - which in the common layout
    # (dialog centered over the main app, scan region elsewhere over the
    # game) it isn't, so it can just stay on screen the whole time.

    def _window_overlaps_region(self):
        try:
            self.win.update_idletasks()
            wx1 = self.win.winfo_rootx()
            wy1 = self.win.winfo_rooty()
            wx2 = wx1 + self.win.winfo_width()
            wy2 = wy1 + self.win.winfo_height()
        except tk.TclError:
            return True  # can't tell - be safe and hide, same as before

        rx, ry, rw, rh = config.SCAN_REGION
        rx2, ry2 = rx + rw, ry + rh
        return wx1 < rx2 and wx2 > rx and wy1 < ry2 and wy2 > ry

    def _capture_unlit(self):
        self._start_capture(is_lit=False)

    def _capture_lit(self):
        self._start_capture(is_lit=True)

    def _start_capture(self, is_lit):
        self.capture_unlit_btn.config(state="disabled")
        self.capture_lit_btn.config(state="disabled")
        hide_window = self._window_overlaps_region()
        threading.Thread(target=self._capture_thread, args=(is_lit, hide_window), daemon=True).start()

    def _capture_thread(self, is_lit, hide_window):
        label = "LIT" if is_lit else "UNLIT"
        if hide_window:
            self.win.after(0, self.win.withdraw)
            self.win.after(0, self.win.update)
        for remaining in (3, 2, 1):
            msg = f"Capturing {label} in {remaining}... (make sure it's actually {label.lower()} right now)"
            self.win.after(0, lambda m=msg: self.status_var.set(m))
            time.sleep(1)
        shot = pyautogui.screenshot(region=config.SCAN_REGION)
        self.win.after(0, self._finish_capture, is_lit, shot)

    def _finish_capture(self, is_lit, shot):
        # deiconify()/raise_above() are harmless no-ops if the window was
        # never withdrawn - simplest to just always call them, rather than
        # threading hide_window through to here too.
        self.win.deiconify()
        ui_utils.raise_above(self.win)
        self.win.grab_set()
        self.win.focus_force()

        bgr = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        if is_lit:
            self.lit_bgr = bgr
            self._tk_lit = self._draw_preview(self.lit_canvas, self.lit_bgr)
            self.lit_label.config(text="captured", fg="#F0F4F5")
        else:
            self.unlit_bgr = bgr
            self._tk_unlit = self._draw_preview(self.unlit_canvas, self.unlit_bgr)
            self.unlit_label.config(text="captured", fg="#F0F4F5")

        self.capture_unlit_btn.config(state="normal")
        self.capture_lit_btn.config(state="normal")
        self._after_capture()

    def _after_capture(self):
        if self.unlit_bgr is not None and self.lit_bgr is None:
            self.status_var.set("Step 2 - trigger the glow (LIT), then click 'Capture Lit'")
        elif self.lit_bgr is not None and self.unlit_bgr is None:
            self.status_var.set("Step 1 - set it back to UNLIT, then click 'Capture Unlit'")
        elif self.unlit_bgr is not None and self.lit_bgr is not None:
            self._auto_calibrate()

    def _reset(self):
        self.unlit_bgr = None
        self.lit_bgr = None
        self.diff_mask = None
        self._pending_lower = None
        self._pending_upper = None
        self._auto_ran = False
        self.unlit_canvas.delete("all")
        self.lit_canvas.delete("all")
        self.unlit_label.config(text="not captured", fg="#A4B1BC")
        self.lit_label.config(text="not captured", fg="#A4B1BC")
        self.result_var.set("Capture both to auto-calibrate.")
        self.tol_slider.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status_var.set("Step 1 - make sure the item is UNLIT, then click 'Capture Unlit'")

    # --- Diff mask -----------------------------------------------------
    # Where the calibration actually happens: find whichever pixels changed
    # between the two captures, not just the border ring. Any local, roughly
    # consistent visual change (border glow, internal highlight, whole-icon
    # brightening) shows up here, wherever it is.

    MIN_DIFF_PIXELS = 8  # below this, treat it as "no real difference found"

    def _compute_diff_mask(self):
        diff = np.linalg.norm(
            self.lit_bgr.astype(np.int16) - self.unlit_bgr.astype(np.int16), axis=2
        )
        # Raw (pre-normalize) magnitude, kept purely for diagnostics. Otsu +
        # NORM_MINMAX below always stretches whatever diff exists to fill
        # 0-255, so a "no difference" verdict after that step can't be told
        # apart from "there was a small real difference" without this.
        self._last_raw_max_diff = float(diff.max())
        diff_norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, mask_u8 = cv2.threshold(diff_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Strip JPEG-ish single-pixel noise WITHOUT erasing real-but-thin
        # features. A blanket 3x3 erosion (the old approach) requires a full
        # 3x3 block of foreground to survive, which wipes out a thin glow
        # ring/outline entirely before dilation ever gets a chance to bring
        # it back - exactly the shape a border-style glow usually has.
        # Connected-component filtering instead only drops truly isolated
        # single pixels (area 1) and keeps everything else, however thin.
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
        cleaned = np.zeros_like(mask_u8)
        for label in range(1, num_labels):
            if stats[label, cv2.CC_STAT_AREA] >= 2:
                cleaned[labels == label] = 255
        mask_u8 = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        return mask_u8 > 0

    def _mask_hsv_pixels(self, bgr, mask):
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return hsv[mask].reshape(-1, 3)

    def _bounds_at_tolerance(self, lit_pixels, tol):
        # Higher tolerance -> wider percentile clip -> looser bounds.
        lo_pct = max(0.5, 10 - tol / 12.0)
        hi_pct = 100 - lo_pct
        h, s, v = lit_pixels[:, 0], lit_pixels[:, 1], lit_pixels[:, 2]
        lower = (
            int(np.clip(np.percentile(h, lo_pct), 0, 179)),
            int(np.clip(np.percentile(s, lo_pct), 0, 255)),
            int(np.clip(np.percentile(v, lo_pct), 0, 255)),
        )
        upper = (int(np.clip(np.percentile(h, hi_pct), 0, 179)), 255, 255)
        return lower, upper

    def _test_bounds(self, lower, upper):
        lit_pct, _ = vision.compute_mask_stats(self.lit_bgr, lower, upper, self.diff_mask)
        unlit_pct, _ = vision.compute_mask_stats(self.unlit_bgr, lower, upper, self.diff_mask)
        return lit_pct, unlit_pct

    def _auto_calibrate(self):
        """Find the changed zone, then search tolerances loosest -> tightest
        and keep the loosest one that still keeps LIT clearly matching and
        UNLIT clearly not matching within that zone."""
        self.diff_mask = self._compute_diff_mask()
        pixel_count = int(np.count_nonzero(self.diff_mask))

        if pixel_count < self.MIN_DIFF_PIXELS:
            self._auto_ran = "no_diff"
            self.diff_mask = None
            self.status_var.set("No difference detected")
            raw_max = getattr(self, "_last_raw_max_diff", 0.0)
            MAX_POSSIBLE_DIFF = 441.7  # ceiling of a 3-channel BGR Euclidean norm
            pct_of_max = raw_max / MAX_POSSIBLE_DIFF * 100.0
            if raw_max < 2.0:
                # Essentially bit-for-bit identical - almost always means the
                # item wasn't actually in a different state for one of the
                # two shots (or the same frame got captured twice), not a
                # calibration/tolerance issue.
                detail = (
                    "The two captures are pixel-for-pixel identical. That means the "
                    "item was in the same state - or the screenshot was taken before "
                    "the glow actually changed - for both shots, not that the glow is subtle."
                )
            else:
                detail = (
                    f"There's a real difference somewhere (peak pixel change: "
                    f"{pct_of_max:.0f}% of the max possible) but it didn't hold together "
                    f"as enough connected pixels to build a reliable watch zone - the "
                    f"changed area may be too small, or the captures may be misaligned."
                )
            self.result_var.set(
                detail + " Make sure the item is clearly UNLIT for step 1 and clearly "
                "LIT (re-hover/re-trigger it during the countdown if needed) for step 2, "
                "then Reset Both and try again."
            )
            self._tk_lit = self._draw_preview(self.lit_canvas, self.lit_bgr)
            self._tk_unlit = self._draw_preview(self.unlit_canvas, self.unlit_bgr)
            self.lit_label.config(text="no change detected", fg="#C24C4C")
            self.unlit_label.config(text="no change detected", fg="#C24C4C")
            return

        region_pct = pixel_count / self.diff_mask.size * 100.0
        lit_pixels = self._mask_hsv_pixels(self.lit_bgr, self.diff_mask)
        best_tol = None
        for tol in range(100, 0, -1):
            lower, upper = self._bounds_at_tolerance(lit_pixels, tol)
            lit_pct, unlit_pct = self._test_bounds(lower, upper)
            if lit_pct >= AUTO_MIN_LIT_MATCH and unlit_pct <= AUTO_MAX_UNLIT_MATCH:
                best_tol = tol
                break
        if best_tol is None:
            # No tolerance cleanly separates them even within the changed
            # zone - fall back to the tightest possible band and say so
            # honestly, rather than pretending this worked. Likely means the
            # "glow" is mostly a brightness shift that doesn't hold a
            # consistent color, or lit/unlit are just too visually similar.
            best_tol = 1
            self._auto_ran = "poor"
        else:
            self._auto_ran = "ok"

        self._region_pct = region_pct
        self.tol_slider.config(state="normal")
        self.tol_var.set(best_tol)
        self.status_var.set("Auto-calibrated - drag Tolerance to adjust, then Save")
        self._refresh_from_slider()

    def _on_tolerance_change(self):
        if self.diff_mask is not None:
            self._refresh_from_slider()

    def _refresh_from_slider(self):
        lit_pixels = self._mask_hsv_pixels(self.lit_bgr, self.diff_mask)
        lower, upper = self._bounds_at_tolerance(lit_pixels, self.tol_var.get())
        lit_pct, unlit_pct = self._test_bounds(lower, upper)
        self._pending_lower, self._pending_upper = lower, upper
        # Sits between the two so a live scan reliably lands on the LIT side.
        self._pending_threshold = round((lit_pct + unlit_pct) / 2, 1)

        good = lit_pct >= AUTO_MIN_LIT_MATCH and unlit_pct <= AUTO_MAX_UNLIT_MATCH
        lit_color = "#8FBF6B" if lit_pct >= AUTO_MIN_LIT_MATCH else "#C24C4C"
        unlit_color = "#8FBF6B" if unlit_pct <= AUTO_MAX_UNLIT_MATCH else "#C24C4C"

        self._tk_lit = self._draw_preview(self.lit_canvas, self.lit_bgr, outline=lit_color, mask=self.diff_mask)
        self._tk_unlit = self._draw_preview(self.unlit_canvas, self.unlit_bgr, outline=unlit_color, mask=self.diff_mask)
        self.lit_label.config(text=f"{lit_pct:.1f}% match (want high)", fg=lit_color)
        self.unlit_label.config(text=f"{unlit_pct:.1f}% match (want low)", fg=unlit_color)

        zone_note = f"Watching {getattr(self, '_region_pct', 0):.1f}% of the region (highlighted). "
        if good:
            self.result_var.set(
                zone_note + f"Good separation - threshold will be set to {self._pending_threshold:.1f}%."
            )
        elif self._auto_ran == "poor":
            self.result_var.set(
                zone_note + "Couldn't find a clean color gap between lit and unlit in that zone - "
                "the change might be more of a brightness shift than a distinct color. "
                "Try Advanced Tuner instead."
            )
        else:
            self.result_var.set(
                zone_note + "Weak separation at this tolerance - try dragging it lower, or Recapture."
            )
        self.save_btn.config(state="normal")

    # --- Save / navigate -----------------------------------------------

    def _save(self):
        if self._pending_lower is None or self.diff_mask is None:
            return
        config.LOWER_GOLD, config.UPPER_GOLD = self._pending_lower, self._pending_upper
        config.MIN_BORDER_MATCH_PERCENT = self._pending_threshold
        config.DIFF_MASK = self.diff_mask
        config.DETECTION_MODE = 'COLOR_MASK'
        # A clean lit-vs-unlit capture in this region is itself decent
        # evidence the region is placed sensibly, so treat it as confirming
        # the scan region too (not just the color/mask).
        config.SCAN_REGION_CONFIRMED = True
        settings_manager.save_settings()
        self.win.destroy()
        if self.on_saved:
            self.on_saved()

    def _open_advanced(self):
        self.win.destroy()
        if self.on_advanced:
            self.on_advanced()