# hsv_tuner.py
#
# Tkinter-based HSV tuner that matches the app's theme. Replaces the old
# OpenCV trackbar window (which looked out of place and behaved oddly in
# frozen exe builds).

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


class HSVTuner:
    PREVIEW_SIZE = 280

    def __init__(self, parent, on_status=None, theme=None):
        self.parent = parent
        self.on_status = on_status
        self._running = True
        self._preview_job = None
        self._tk_img = None

        theme = theme or {}
        self.bg = theme.get("bg", "#12161C")
        self.panel = theme.get("panel", "#1C222A")
        self.border = theme.get("border", "#37424C")
        self.gold = theme.get("gold", "#80DDC0")
        self.text = theme.get("text", "#F0F4F5")
        self.text_dim = theme.get("text_dim", "#A4B1BC")
        self.btn_bg = theme.get("btn_bg", "#29343E")
        self.ok = theme.get("ok", "#8FBF6B")
        self.bad = theme.get("bad", "#C24C4C")

        self.win = tk.Toplevel(parent)
        self.win.configure(bg=self.bg)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        ui_utils.add_title_strip(
            self.win, self.win, "ADVANCED HSV TUNER",
            bg=self.bg, panel_bg=self.panel, fg=self.gold, fg_dim=self.text_dim,
            close_command=self._cancel
        )
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        body = tk.Frame(self.win, bg=self.bg, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        preview_row = tk.Frame(body, bg=self.bg)
        preview_row.pack(fill="x", pady=(0, 10))

        self.preview_canvas = tk.Canvas(
            preview_row, width=self.PREVIEW_SIZE, height=self.PREVIEW_SIZE // 2,
            highlightthickness=0, bg="#000000"
        )
        self.preview_canvas.pack()

        self.match_var = tk.StringVar(value="Waiting for preview...")
        self.match_label = tk.Label(
            body, textvariable=self.match_var, bg=self.bg, fg=self.text,
            font=("Segoe UI", 10, "bold")
        )
        self.match_label.pack(anchor="w", pady=(0, 8))

        sliders = tk.Frame(body, bg=self.bg)
        sliders.pack(fill="x")

        self.vars = {}
        specs = [
            ("H Min", "hmin", 0, 179, config.LOWER_GOLD[0]),
            ("S Min", "smin", 0, 255, config.LOWER_GOLD[1]),
            ("V Min", "vmin", 0, 255, config.LOWER_GOLD[2]),
            ("H Max", "hmax", 0, 179, config.UPPER_GOLD[0]),
            ("S Max", "smax", 0, 255, config.UPPER_GOLD[1]),
            ("V Max", "vmax", 0, 255, config.UPPER_GOLD[2]),
            ("Min Match %", "match", 0, 100, int(config.MIN_BORDER_MATCH_PERCENT)),
        ]
        for label, key, lo, hi, val in specs:
            self._add_slider(sliders, label, key, lo, hi, val)

        hint = tk.Label(
            body,
            text="Green border = match  ·  Red = no match  ·  Right pane = color mask",
            bg=self.bg, fg=self.text_dim, font=("Segoe UI", 8), wraplength=360, justify="left"
        )
        hint.pack(anchor="w", pady=(6, 10))

        btn_row = tk.Frame(body, bg=self.bg)
        btn_row.pack(fill="x")
        tk.Button(
            btn_row, text="Save", command=self._save,
            bg=self.btn_bg, fg=self.ok, relief="flat", padx=12, pady=6, cursor="hand2"
        ).pack(side="right")
        tk.Button(
            btn_row, text="Cancel", command=self._cancel,
            bg=self.btn_bg, fg=self.bad, relief="flat", padx=12, pady=6, cursor="hand2"
        ).pack(side="right", padx=(0, 8))

        ui_utils.finalize_toplevel(self.win, parent=parent)
        self._schedule_preview()

    def _add_slider(self, parent, label, key, lo, hi, val):
        row = tk.Frame(parent, bg=self.bg)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=self.bg, fg=self.text, font=("Segoe UI", 8), width=11, anchor="w").pack(side="left")
        var = tk.IntVar(value=val)
        self.vars[key] = var
        scale = tk.Scale(
            row, from_=lo, to=hi, orient="horizontal", variable=var,
            command=lambda _v: self._schedule_preview(),
            bg=self.bg, fg=self.gold, troughcolor=self.btn_bg,
            highlightthickness=0, activebackground=self.gold, showvalue=True, length=240
        )
        scale.pack(side="left", fill="x", expand=True)

    def _values(self):
        return (
            self.vars["hmin"].get(), self.vars["smin"].get(), self.vars["vmin"].get(),
            self.vars["hmax"].get(), self.vars["smax"].get(), self.vars["vmax"].get(),
            self.vars["match"].get(),
        )

    def _schedule_preview(self):
        if self._preview_job:
            self.win.after_cancel(self._preview_job)
        self._preview_job = self.win.after(80, self._update_preview)

    def _update_preview(self):
        if not self._running:
            return
        try:
            screenshot = pyautogui.screenshot(region=config.SCAN_REGION)
        except Exception as e:
            self.match_var.set(f"Scan error: {e}")
            self.match_label.config(fg=self.bad)
            return

        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        hmin, smin, vmin, hmax, smax, vmax, min_match = self._values()
        lower = np.array([hmin, smin, vmin])
        upper = np.array([hmax, smax, vmax])

        match_pct, color_mask, _ = vision.compute_border_stats(
            img, lower, upper, config.BORDER_THICKNESS
        )
        is_match = match_pct >= min_match

        preview = img.copy()
        feedback = (143, 191, 107) if is_match else (76, 76, 194)  # BGR
        h, w = preview.shape[:2]
        thick = max(1, min(config.BORDER_THICKNESS, h // 2, w // 2))
        cv2.rectangle(preview, (0, 0), (w - 1, h - 1), feedback, thick)

        mask_bgr = cv2.cvtColor(color_mask, cv2.COLOR_GRAY2BGR)
        stacked = np.hstack((preview, mask_bgr))
        target_w = self.PREVIEW_SIZE
        target_h = max(1, target_w * stacked.shape[0] // max(stacked.shape[1], 1))
        stacked = cv2.resize(stacked, (target_w, target_h), interpolation=cv2.INTER_NEAREST)

        rgb = cv2.cvtColor(stacked, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        self._tk_img = ImageTk.PhotoImage(pil)
        self.preview_canvas.config(height=target_h)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

        status = f"{'MATCH' if is_match else 'NO MATCH'}  ·  {match_pct:.1f}% (need {min_match}%)"
        self.match_var.set(status)
        self.match_label.config(fg=self.ok if is_match else self.bad)

        if self._running:
            self._preview_job = self.win.after(120, self._update_preview)

    def _save(self):
        hmin, smin, vmin, hmax, smax, vmax, min_match = self._values()
        config.LOWER_GOLD = (hmin, smin, vmin)
        config.UPPER_GOLD = (hmax, smax, vmax)
        config.MIN_BORDER_MATCH_PERCENT = float(min_match)
        config.DETECTION_MODE = "COLOR_BORDER"
        # Tuning a live preview against this region is decent evidence the
        # region itself is placed sensibly, so treat it as confirmed too.
        config.SCAN_REGION_CONFIRMED = True
        settings_manager.save_settings()
        if self.on_status:
            self.on_status("HSV SAVED", self.ok)
        self._close()

    def _cancel(self):
        if self.on_status:
            self.on_status("HSV TUNING CANCELLED", self.bad)
        self._close()

    def _close(self):
        self._running = False
        if self._preview_job:
            try:
                self.win.after_cancel(self._preview_job)
            except Exception:
                pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.destroy()

    @staticmethod
    def open(parent, on_status=None, theme=None):
        """Open tuner on the main thread."""
        return HSVTuner(parent, on_status=on_status, theme=theme)
