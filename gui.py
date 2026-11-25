# gui.py
import tkinter as tk
from tkinter import filedialog
import threading
import time
import json
import pyautogui
import keyboard

import config
import regex_manager
import settings_manager
import ui_utils
import license_manager
from overlay import RegionOverlay
from crafter import AutoCrafter


class CrafterGUI:
    def __init__(self, root, parent, close_app):
        # Apply any previously saved scan region / HSV tuning on top of the
        # config.py defaults before anything else reads from config.
        settings_manager.load_settings()

        self.root = root
        self.close_app = close_app
        self.bg_color = "#12161C"          # near-black warm background
        self.panel_color = "#1C222A"       # dark panel
        self.border_gold = "#37424C"       # muted gold-brown hairline border
        self.gold = "#80DDC0"              # primary gold accent
        self.gold_bright = "#AFF6DF"       # hover / active gold
        self.text_color = "#F0F4F5"        # parchment text
        self.text_dim = "#A4B1BC"          # secondary text
        self.btn_bg = "#29343E"
        self.btn_hover = "#394953"

        # rarity-inspired status colors
        self.color_running = "#8FBF6B"      # muted green
        self.color_stopped = "#C24C4C"      # muted red
        self.color_found = "#6EA8D6"        # magic-item blue
        self.color_warn = "#D6A24C"         # amber / starting

        self.title_font = ("Segoe UI", 10)
        self.header_font = ("Segoe UI", 10, "bold")
        self.body_font = ("Segoe UI", 9)
        self.mono_font = ("Consolas", 8)

        self.shell = tk.Frame(parent, bg=self.bg_color)
        self.shell.pack(fill="both", expand=True)

        self.overlay = RegionOverlay()
        self.crafter = AutoCrafter(self.update_status)

        self.countdown = 0
        self.is_starting = False
        self.regex_data = regex_manager.load_regex_data()
        migrated = False
        for item in self.regex_data:
            if "category" not in item:
                item["category"] = "General"
                migrated = True
        if migrated:
            regex_manager.save_regex_data(self.regex_data)
        self.current_category = "All"
        self.category_order = regex_manager.load_category_order()
        self.sync_category_order()

        # Drag-and-drop state (regex rows + category tabs)
        self._dragging_idx = None
        self._dragging_row_state = None
        self._row_moved = False
        self._visible_rows = []
        self._dragging_tab = None
        self._dragging_tab_state = None
        self._tab_moved = False
        self._visible_tabs = []

        self._hotkeys_registered = False
        self._tray = None
        self._quitting = False
        self.build_ui()
        self._start_tray()

    # --- Thread-safety helpers -------------------------------------------------
    # AutoCrafter runs its loop on a worker thread, and the `keyboard` library
    # fires hotkey callbacks on its own internal thread. Tkinter widgets may
    # only be touched from the main thread, so everything that can be called
    # from those threads gets marshalled through root.after(0, ...).

    def update_status(self, text, color):
        self.root.after(0, self._update_status_ui, text, color)

    def _update_status_ui(self, text, color):
        self.status_var.set(text)
        self.status_label.config(fg=color)

    # --- Always-on-top toggle -----------------------------------------------
    def toggle_always_on_top(self):
        config.ALWAYS_ON_TOP = not config.ALWAYS_ON_TOP
        self.root.attributes("-topmost", config.ALWAYS_ON_TOP)
        self._refresh_topmost_btn()
        settings_manager.save_settings()
        self.update_status(
            "ALWAYS ON TOP: ON" if config.ALWAYS_ON_TOP else "ALWAYS ON TOP: OFF",
            self.color_running if config.ALWAYS_ON_TOP else self.text_dim
        )

    def _refresh_topmost_btn(self):
        self.topmost_btn.config(
            fg=self.gold if config.ALWAYS_ON_TOP else self.text_dim,
            activeforeground=self.gold_bright if config.ALWAYS_ON_TOP else self.text_color,
        )

    def _ensure_pinned(self):
        """Called from initiate_start() - crafting while the window is
        buried behind a game/browser is the main reason to have Pin at
        all, so Start turns it on automatically if it's off instead of
        relying on the user to remember beforehand. Deliberately doesn't
        go through toggle_always_on_top()'s update_status() call: that's
        queued via root.after(0, ...) and would land a tick later and
        stomp the "STARTING IN n..." countdown text that's about to show."""
        if not config.ALWAYS_ON_TOP:
            config.ALWAYS_ON_TOP = True
            self.root.attributes("-topmost", True)
            self._refresh_topmost_btn()
            settings_manager.save_settings()

    # --- UI Building Methods -----------------------------------------------
    def create_flat_button(self, parent, text, command, bg=None, fg=None, font=None):
        btn_bg = bg if bg else self.btn_bg
        btn_fg = fg if fg else self.gold
        btn = tk.Button(
            parent, text=text, command=command, bg=btn_bg, fg=btn_fg,
            relief="flat", bd=0, activebackground=self.btn_hover, activeforeground=self.gold_bright,
            font=font or self.header_font, padx=10, pady=6, cursor="hand2",
            highlightthickness=1, highlightbackground=self.border_gold, highlightcolor=self.border_gold
        )
        return btn

    def gold_divider(self, parent):
        tk.Frame(parent, bg=self.border_gold, height=1).pack(fill="x", pady=(0, 0))

    def _build_trial_footer(self):
        # Packed first with side=bottom so it stays under both tabs.
        self._trial_locked = False
        self.trial_footer = tk.Frame(self.shell, bg=self.panel_color)
        tk.Frame(self.trial_footer, bg=self.border_gold, height=1).pack(fill="x")
        self.trial_var = tk.StringVar(value="")
        self.trial_label = tk.Label(
            self.trial_footer, textvariable=self.trial_var, bg=self.panel_color,
            fg=self.text_dim, font=("Segoe UI", 8)
        )
        self.trial_label.pack(pady=4)
        # Must pack BEFORE main_container so the crafter tab cannot eat this space.
        if license_manager.trial_time_left() is not None:
            self._show_trial_footer()

    def _show_trial_footer(self):
        if not self.trial_footer.winfo_ismapped():
            kwargs = {"side": "bottom", "fill": "x"}
            if getattr(self, "main_container", None) is not None:
                kwargs["before"] = self.main_container
            self.trial_footer.pack(**kwargs)


    def _tick_trial_footer(self):
        remaining = license_manager.trial_time_left()
        text = license_manager.format_trial_remaining(remaining)
        if text is None:
            self.trial_footer.pack_forget()
            return
        self._show_trial_footer()
        self.trial_var.set(text)
        if remaining <= 0:
            self.trial_label.config(fg=self.color_stopped)
            self._on_trial_expired()
            return
        if remaining < 3600:
            self.trial_label.config(fg=self.color_warn)
        else:
            self.trial_label.config(fg=self.text_dim)
        self.root.after(1000, self._tick_trial_footer)

    def _on_trial_expired(self):
        if self._trial_locked:
            return
        self._trial_locked = True
        self.cancel_start()
        self.crafter.stop()
        self.update_status("TRIAL ENDED", self.color_stopped)
        try:
            self.start_btn.config(state="disabled")
        except tk.TclError:
            pass

    def build_ui(self):
        self.build_title_bar()
        self.build_tab_bar()

        self._build_trial_footer()

        self.main_container = tk.Frame(self.shell, bg=self.bg_color)
        self.main_container.pack(fill="both", expand=True)

        self.build_crafter_tab()
        self.build_regex_tab()
        self.build_settings_tab()

        self.show_tab('crafter')
        self._tick_trial_footer()
        self._tick_stats()

    def build_title_bar(self):
        title_bar = tk.Frame(self.shell, bg=self.panel_color, bd=0)
        title_bar.pack(fill="x")
        self.gold_divider(self.shell)

        tk.Label(title_bar, text="Auto Crafter", bg=self.panel_color, fg=self.text_color,
                 font=("Segoe UI", 20, "bold")).pack(side="left", padx=20, pady=12)
        self.create_flat_button(title_bar, "Hide to tray", self.minimize_to_tray).pack(side="right", padx=8)
        self.topmost_btn = tk.Button(
            title_bar, text="Pin window", bg=self.panel_color, bd=0,
            activebackground=self.panel_color, cursor="hand2",
            font=("Segoe UI", 8, "bold"), command=self.toggle_always_on_top
        )
        self.topmost_btn.pack(side="right", padx=(0, 2))
        self._refresh_topmost_btn()

    def build_tab_bar(self):
        tab_bar = tk.Frame(self.shell, bg=self.bg_color)
        tab_bar.pack(fill="x")

        # Letter-spaced style ("C R A F T E R") worked for two tabs but gets
        # cramped with three at this window width, so plain text below.
        self.tab_crafter_btn = tk.Button(
            tab_bar, text="CRAFTER", bg=self.bg_color, fg=self.gold, relief="flat", bd=0,
            font=self.header_font, command=lambda: self.show_tab('crafter'), cursor="hand2", pady=8
        )
        self.tab_crafter_btn.pack(side="left", expand=True, fill="x")

        self.tab_regex_btn = tk.Button(
            tab_bar, text="REGEX VAULT", bg=self.bg_color, fg=self.text_dim, relief="flat", bd=0,
            font=self.header_font, command=lambda: self.show_tab('regex'), cursor="hand2", pady=8
        )
        self.tab_regex_btn.pack(side="left", expand=True, fill="x")

        self.tab_settings_btn = tk.Button(
            tab_bar, text="SETTINGS", bg=self.bg_color, fg=self.text_dim, relief="flat", bd=0,
            font=self.header_font, command=lambda: self.show_tab('settings'), cursor="hand2", pady=8
        )
        self.tab_settings_btn.pack(side="left", expand=True, fill="x")

        self.tab_underline = tk.Frame(self.shell, bg=self.gold, height=2)
        self.tab_underline.pack(fill="x")

    def show_tab(self, tab_name):
        self.active_tab = tab_name
        frames = {
            'crafter': self.crafter_frame,
            'regex': self.regex_frame,
            'settings': self.settings_frame,
        }
        buttons = {
            'crafter': self.tab_crafter_btn,
            'regex': self.tab_regex_btn,
            'settings': self.tab_settings_btn,
        }
        for name, frame in frames.items():
            if name == tab_name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for name, btn in buttons.items():
            btn.config(fg=self.gold if name == tab_name else self.text_dim)

        if tab_name == 'crafter':
            self._resume_hotkeys()
        else:
            # Global keyboard hooks swallow keystrokes in Entry widgets on
            # Windows (especially in frozen exe builds). Regex Vault and
            # Settings both have entries/modals, so pause while either is
            # active.
            self._pause_hotkeys()

    def _panel(self, parent):
        outer = tk.Frame(parent, bg=self.border_gold)
        inner = tk.Frame(outer, bg=self.panel_color, padx=15, pady=15)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    # --- Crafter Tab Layout ---
    def build_crafter_tab(self):
        self.crafter_frame = tk.Frame(self.main_container, bg=self.bg_color)

        self.status_var = tk.StringVar(value="STOPPED")
        self.status_label = tk.Label(self.crafter_frame, textvariable=self.status_var, bg=self.bg_color,
                                      fg=self.color_stopped, font=("Segoe UI", 14, "bold"))
        self.status_label.pack(pady=(18, 2))

        # Craft counter: live clicks/time while running, last-run summary
        # once stopped. Ticked in _tick_stats().
        self.stats_var = tk.StringVar(value="")
        self.stats_label = tk.Label(self.crafter_frame, textvariable=self.stats_var, bg=self.bg_color,
                                     fg=self.text_dim, font=("Segoe UI", 8))
        self.stats_label.pack(pady=(0, 4))

        # First-run guidance: stays visible until a scan region has been
        # explicitly confirmed on this machine, so it's obvious what to do
        # before hitting Start rather than getting a cryptic failure.
        self.region_hint_var = tk.StringVar(value="")
        self.region_hint_label = tk.Label(self.crafter_frame, textvariable=self.region_hint_var,
                                           bg=self.bg_color, fg=self.color_warn,
                                           font=("Segoe UI", 8, "bold"), wraplength=360, justify="center")
        self.region_hint_label.pack(pady=(0, 6))
        self._update_region_hint()

        controls_outer, controls = self._panel(self.crafter_frame)
        controls_outer.pack(fill="x", padx=20, pady=5)

        self.mode_btn = self.create_flat_button(controls, "MODE: FULL AUTO", self.toggle_mode,
                                                  bg=self.btn_bg, fg=self.color_running)
        self.mode_btn.pack(fill="x", pady=(0, 10))

        btn_frame = tk.Frame(controls, bg=self.panel_color)
        btn_frame.pack(fill="x", pady=(0, 10))

        self.start_btn = self.create_flat_button(btn_frame, self._start_label(), self.initiate_start,
                                                   bg=self.btn_bg, fg=self.gold)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.stop_btn = self.create_flat_button(btn_frame, "STOP", self.crafter.stop,
                                                  bg=self.btn_bg, fg=self.color_stopped)
        self.stop_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.hotkey_info_var = tk.StringVar(value="")
        self._update_hotkey_info()
        info = tk.Label(self.crafter_frame, textvariable=self.hotkey_info_var,
                         bg=self.bg_color, fg=self.text_dim, font=self.mono_font)
        info.pack(side="bottom", pady=(6, 8))

    # --- Settings Tab Layout ---
    def build_settings_tab(self):
        self.settings_frame = tk.Frame(self.main_container, bg=self.bg_color)

        # The tab grew past a fixed-size window's worth of content once
        # Click Behavior (start delay, hold, burst) was added, so it
        # scrolls instead of clipping - same canvas pattern as the regex
        # list, but no visible Scrollbar widget (its default gray 3D look
        # clashed with the dark/gold theme everywhere else) - scroll via
        # mouse wheel only, same as the regex list already supports.
        settings_canvas = tk.Canvas(self.settings_frame, bg=self.bg_color, highlightthickness=0)
        settings_scroll_frame = tk.Frame(settings_canvas, bg=self.bg_color)

        settings_scroll_frame.bind(
            "<Configure>",
            lambda e: settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
        )

        settings_window = settings_canvas.create_window((0, 0), window=settings_scroll_frame, anchor="nw")
        settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfig(settings_window, width=e.width))

        settings_canvas.pack(side="left", fill="both", expand=True)

        controls_outer, controls = self._panel(settings_scroll_frame)
        controls_outer.pack(fill="x", padx=20, pady=(20, 5))

        tk.Label(controls, text="CALIBRATION & UTILITIES", bg=self.panel_color,
                 fg=self.gold, font=("Segoe UI", 8, "bold")).pack(pady=(0, 8))

        self.create_flat_button(controls, "Set Scan Region", self.run_region_finder,
                                 font=self.body_font).pack(fill="x", pady=2)
        self.create_flat_button(controls, "Toggle Green Overlay", self.overlay.toggle,
                                 font=self.body_font).pack(fill="x", pady=2)
        self.create_flat_button(controls, "Calibrate Color (Click)", self.run_calibrator,
                                 font=self.body_font).pack(fill="x", pady=2)
        self.create_flat_button(controls, "Rebind Hotkeys", self.run_hotkey_editor,
                                 font=self.body_font).pack(fill="x", pady=2)
        tk.Button(
            controls, text="advanced HSV tuner", command=self.run_hsv_tuner,
            bg=self.panel_color, fg=self.text_dim, relief="flat", bd=0,
            font=("Segoe UI", 7, "underline"), cursor="hand2"
        ).pack(pady=(2, 0))

        settings_outer, settings = self._panel(settings_scroll_frame)
        settings_outer.pack(fill="x", padx=20, pady=5)

        tk.Label(settings, text="CLICK INTERVAL (SEC) — AUTO MODE ONLY", bg=self.panel_color,
                 fg=self.gold, font=("Segoe UI", 8, "bold")).pack()

        time_frame = tk.Frame(settings, bg=self.panel_color)
        time_frame.pack(pady=8)

        self.min_var = tk.DoubleVar(value=config.CLICK_INTERVAL_MIN)
        self.max_var = tk.DoubleVar(value=config.CLICK_INTERVAL_MAX)

        tk.Label(time_frame, text="Min:", bg=self.panel_color, fg=self.text_color, font=self.body_font).pack(side="left")
        min_entry = tk.Entry(time_frame, textvariable=self.min_var, width=5, bg=self.btn_bg, fg=self.text_color,
                  relief="flat", insertbackground=self.gold, highlightthickness=1,
                  highlightbackground=self.border_gold)
        min_entry.pack(side="left", padx=(5, 15))

        tk.Label(time_frame, text="Max:", bg=self.panel_color, fg=self.text_color, font=self.body_font).pack(side="left")
        max_entry = tk.Entry(time_frame, textvariable=self.max_var, width=5, bg=self.btn_bg, fg=self.text_color,
                  relief="flat", insertbackground=self.gold, highlightthickness=1,
                  highlightbackground=self.border_gold)
        max_entry.pack(side="left", padx=5)
        for entry in (min_entry, max_entry):
            entry.bind("<FocusIn>", lambda e: self._pause_hotkeys())
            entry.bind("<FocusOut>", lambda e: self._resume_hotkeys_if_crafter())

        self.create_flat_button(settings, "Save Intervals", self.save_intervals,
                                 font=self.body_font).pack(fill="x", pady=(10, 4))

        # --- Click Behavior: start delay, hold duration, burst mode ---
        behavior_outer, behavior = self._panel(settings_scroll_frame)
        behavior_outer.pack(fill="x", padx=20, pady=(5, 20))

        tk.Label(behavior, text="CLICK BEHAVIOR", bg=self.panel_color,
                 fg=self.gold, font=("Segoe UI", 8, "bold")).pack()

        behavior_entries = []

        def _labeled_row(parent, label_text, var, width=5):
            row = tk.Frame(parent, bg=self.panel_color)
            row.pack(pady=3)
            tk.Label(row, text=label_text, bg=self.panel_color, fg=self.text_color,
                     font=self.body_font).pack(side="left")
            entry = tk.Entry(row, textvariable=var, width=width, bg=self.btn_bg, fg=self.text_color,
                              relief="flat", insertbackground=self.gold, highlightthickness=1,
                              highlightbackground=self.border_gold)
            entry.pack(side="left", padx=(5, 0))
            behavior_entries.append(entry)
            return row

        def _min_max_row(parent, label_text, min_var, max_var, width=5):
            row = tk.Frame(parent, bg=self.panel_color)
            row.pack(pady=3)
            tk.Label(row, text=f"{label_text} Min:", bg=self.panel_color, fg=self.text_color,
                     font=self.body_font).pack(side="left")
            min_entry = tk.Entry(row, textvariable=min_var, width=width, bg=self.btn_bg, fg=self.text_color,
                                  relief="flat", insertbackground=self.gold, highlightthickness=1,
                                  highlightbackground=self.border_gold)
            min_entry.pack(side="left", padx=(5, 15))
            tk.Label(row, text="Max:", bg=self.panel_color, fg=self.text_color,
                     font=self.body_font).pack(side="left")
            max_entry = tk.Entry(row, textvariable=max_var, width=width, bg=self.btn_bg, fg=self.text_color,
                                  relief="flat", insertbackground=self.gold, highlightthickness=1,
                                  highlightbackground=self.border_gold)
            max_entry.pack(side="left", padx=5)
            behavior_entries.extend([min_entry, max_entry])
            return row

        self.start_delay_var = tk.DoubleVar(value=config.START_DELAY_SECONDS)
        _labeled_row(behavior, "Start Delay (sec):", self.start_delay_var)

        self.hold_min_var = tk.DoubleVar(value=config.CLICK_HOLD_MIN)
        self.hold_max_var = tk.DoubleVar(value=config.CLICK_HOLD_MAX)
        _min_max_row(behavior, "Click Hold (sec)", self.hold_min_var, self.hold_max_var)

        self.burst_toggle_btn = self.create_flat_button(
            behavior, self._burst_label(), self.toggle_burst_mode,
            bg=self.btn_bg, fg=self.color_running if config.BURST_MODE_ENABLED else self.text_dim,
            font=self.body_font
        )
        self.burst_toggle_btn.pack(fill="x", pady=(8, 6))

        self.burst_clicks_min_var = tk.IntVar(value=config.BURST_CLICKS_MIN)
        self.burst_clicks_max_var = tk.IntVar(value=config.BURST_CLICKS_MAX)
        _min_max_row(behavior, "Burst Size", self.burst_clicks_min_var, self.burst_clicks_max_var, width=4)

        self.burst_interval_min_var = tk.DoubleVar(value=config.BURST_INTERVAL_MIN)
        self.burst_interval_max_var = tk.DoubleVar(value=config.BURST_INTERVAL_MAX)
        _min_max_row(behavior, "Burst Interval (sec)", self.burst_interval_min_var, self.burst_interval_max_var)

        self.burst_rest_min_var = tk.DoubleVar(value=config.BURST_REST_MIN)
        self.burst_rest_max_var = tk.DoubleVar(value=config.BURST_REST_MAX)
        _min_max_row(behavior, "Rest (sec)", self.burst_rest_min_var, self.burst_rest_max_var)

        tk.Label(
            behavior,
            text="Burst mode clicks fast for a few reps, then rests briefly before the next burst.",
            bg=self.panel_color, fg=self.text_dim, font=("Segoe UI", 8), wraplength=280, justify="center"
        ).pack(pady=(6, 0))

        for entry in behavior_entries:
            entry.bind("<FocusIn>", lambda e: self._pause_hotkeys())
            entry.bind("<FocusOut>", lambda e: self._resume_hotkeys_if_crafter())

        self.create_flat_button(behavior, "Save Click Behavior", self.save_click_behavior,
                                 font=self.body_font).pack(fill="x", pady=(10, 4))

        # Bind wheel-scroll now that every child widget exists - binding
        # only the bare canvas earlier isn't enough, since the mouse is
        # almost always over some label/entry/button inside it rather
        # than the canvas background itself. Same recursive-bind pattern
        # the regex list uses after it rebuilds its rows.
        self._bind_mousewheel(settings_canvas)
        settings_canvas._mousewheel_binder()

    # --- Regex Tab Layout ---
    def build_regex_tab(self):
        self.regex_frame = tk.Frame(self.main_container, bg=self.bg_color)

        # --- Top action row: Add / Export / Import (no more full-time form eating space) ---
        action_frame = tk.Frame(self.regex_frame, bg=self.bg_color, padx=20)
        action_frame.pack(fill="x", pady=(16, 8))

        self.create_flat_button(action_frame, "+ ADD ENTRY", lambda: self.open_regex_modal("add"),
                                 bg=self.btn_bg, fg=self.gold).pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.create_flat_button(action_frame, "EXPORT", self.export_regex_vault,
                                 bg=self.btn_bg, fg=self.text_color, font=self.body_font).pack(
            side="left", expand=True, fill="x", padx=5)
        self.create_flat_button(action_frame, "IMPORT", self.import_regex_vault,
                                 bg=self.btn_bg, fg=self.text_color, font=self.body_font).pack(
            side="right", expand=True, fill="x", padx=(5, 0))

        # --- Category tab strip (drag a tab left/right to reorder) ---
        tabs_outer = tk.Frame(self.regex_frame, bg=self.bg_color, padx=20)
        tabs_outer.pack(fill="x", pady=(4, 8))

        tabs_scroll_outer = tk.Frame(tabs_outer, bg=self.border_gold)
        tabs_scroll_outer.pack(fill="x")
        self.category_tabs_canvas = tk.Canvas(tabs_scroll_outer, bg=self.panel_color, highlightthickness=0, height=34)
        self.category_tabs_canvas.pack(fill="x", padx=1, pady=1)
        self.category_tabs_frame = tk.Frame(self.category_tabs_canvas, bg=self.panel_color)
        self.category_tabs_canvas.create_window((0, 0), window=self.category_tabs_frame, anchor="nw")
        self.category_tabs_frame.bind(
            "<Configure>",
            lambda e: self.category_tabs_canvas.configure(scrollregion=self.category_tabs_canvas.bbox("all"))
        )
        self._bind_mousewheel(self.category_tabs_canvas, horizontal=True)

        list_container = tk.Frame(self.regex_frame, bg=self.bg_color, padx=20)
        list_container.pack(fill="both", expand=True, pady=(0, 15))

        self.canvas = tk.Canvas(list_container, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=self.bg_color)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self._regex_list_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=360)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._regex_list_window, width=e.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._bind_mousewheel(self.canvas)

        self.refresh_regex_list()

    def _bind_mousewheel(self, widget, horizontal=False):
        # Windows/macOS use <MouseWheel> with event.delta; Linux uses Button-4/5.
        # Binding directly to the canvas (rather than bind_all) keeps this scoped
        # to the widget under the cursor so it doesn't hijack scrolling elsewhere.
        def on_wheel(event):
            direction = -1 if event.delta > 0 else 1
            if horizontal:
                widget.xview_scroll(direction, "units")
            else:
                widget.yview_scroll(direction, "units")

        def on_wheel_linux(event, direction):
            if horizontal:
                widget.xview_scroll(direction, "units")
            else:
                widget.yview_scroll(direction, "units")

        def bind_recursive(w):
            w.bind("<MouseWheel>", on_wheel)
            w.bind("<Button-4>", lambda e: on_wheel_linux(e, -1))
            w.bind("<Button-5>", lambda e: on_wheel_linux(e, 1))
            for child in w.winfo_children():
                bind_recursive(child)

        widget.bind("<MouseWheel>", on_wheel)
        widget.bind("<Button-4>", lambda e: on_wheel_linux(e, -1))
        widget.bind("<Button-5>", lambda e: on_wheel_linux(e, 1))
        # Re-bind whenever child widgets are added (rows/tabs get rebuilt on refresh)
        widget._mousewheel_binder = lambda: bind_recursive(widget)

    def open_regex_modal(self, mode="add", idx=None):
        """One dialog handles both add and edit - saves the vertical space the
        old always-visible form used to eat, and gives Edit somewhere to live."""
        self._pause_hotkeys()
        modal = tk.Toplevel(self.root)
        modal.configure(bg=self.panel_color)
        modal.resizable(False, False)
        modal.transient(self.root)
        modal.overrideredirect(True)
        # Main window is always-on-top, so this needs to be too or it can
        # render behind it despite having input focus (grab_set).
        modal.attributes("-topmost", True)
        ui_utils.add_title_strip(
            modal, modal, "Add Regex Entry" if mode == "add" else "Edit Regex Entry",
            bg=self.bg_color, panel_bg=self.panel_color, fg=self.gold, fg_dim=self.text_dim,
            close_command=modal.destroy, font=self.header_font
        )
        modal.grab_set()
        modal.bind("<Destroy>", lambda e: self._on_regex_modal_closed(), add="+")

        item = self.regex_data[idx] if mode == "edit" else {
            "title": "", "regex": "",
            "category": self.current_category if self.current_category != "All" else "General"
        }

        def labeled_entry(label_text, value):
            tk.Label(modal, text=label_text, bg=self.panel_color, fg=self.text_color,
                     font=self.body_font).pack(anchor="w", padx=15, pady=(12, 0))
            entry = tk.Entry(modal, width=42, bg=self.btn_bg, fg=self.text_color, relief="flat",
                              insertbackground=self.gold, font=self.body_font,
                              highlightthickness=1, highlightbackground=self.border_gold)
            entry.insert(0, value)
            entry.pack(padx=15, pady=(2, 0), ipady=3)
            return entry

        title_entry = labeled_entry("Title:", item["title"])
        regex_entry = labeled_entry("Regex String:", item["regex"])
        category_entry = labeled_entry("Category:", item.get("category", "General"))

        def do_save():
            title = title_entry.get().strip()
            regex = regex_entry.get().strip()
            category = category_entry.get().strip() or "General"
            if not title or not regex:
                return
            if mode == "add":
                self.regex_data.append({"title": title, "regex": regex, "category": category})
            else:
                self.regex_data[idx] = {"title": title, "regex": regex, "category": category}
            regex_manager.save_regex_data(self.regex_data)
            self.current_category = category
            modal.destroy()
            self.refresh_regex_list()

        btn_row = tk.Frame(modal, bg=self.panel_color)
        btn_row.pack(fill="x", padx=15, pady=15)
        self.create_flat_button(btn_row, "Save", do_save, bg=self.btn_bg, fg=self.color_running).pack(
            side="left", expand=True, fill="x", padx=(0, 5))
        self.create_flat_button(btn_row, "Cancel", modal.destroy, bg=self.btn_bg, fg=self.color_stopped).pack(
            side="right", expand=True, fill="x", padx=(5, 0))

        ui_utils.finalize_toplevel(modal, parent=self.root)
        title_entry.focus_set()
        modal.focus_force()

    def _on_regex_modal_closed(self):
        # Resume only if we're not still on the regex tab (tab keeps hooks off).
        if self.regex_frame.winfo_ismapped():
            self._pause_hotkeys()
        else:
            self._resume_hotkeys()

    def sync_category_order(self):
        """Keeps the persisted drag order in sync with what's actually in the
        vault: categories that got deleted drop out, new ones land at the end."""
        present = []
        for item in self.regex_data:
            cat = item.get("category", "General")
            if cat not in present:
                present.append(cat)
        self.category_order = [c for c in self.category_order if c in present] + \
                               [c for c in present if c not in self.category_order]

    def select_category(self, cat):
        self.current_category = cat
        self.refresh_regex_list()

    def refresh_category_tabs(self):
        self.sync_category_order()
        for widget in self.category_tabs_frame.winfo_children():
            widget.destroy()
        self._visible_tabs = []

        categories = ["All"] + self.category_order
        if self.current_category not in categories:
            self.current_category = "All"

        for cat in categories:
            is_active = (cat == self.current_category)
            tab_state = {"cat": cat}
            btn = tk.Button(
                self.category_tabs_frame, text=cat.upper(), bg=self.btn_hover if is_active else self.btn_bg,
                fg=self.gold_bright if is_active else self.text_dim, relief="flat", bd=0,
                activebackground=self.btn_hover, activeforeground=self.gold_bright,
                font=("Segoe UI", 8, "bold"), padx=10, pady=5, cursor="hand2",
                # "All" isn't draggable, so a plain Tk command is fine for it.
                # Draggable tabs are NOT given one - see _tab_drag_end for why.
                command=(lambda st=tab_state: self.select_category(st["cat"])) if cat == "All" else None
            )
            btn.pack(side="left", padx=(0, 4), pady=4)
            if cat != "All":
                btn.bind("<ButtonPress-1>", lambda e, st=tab_state: self._tab_drag_start(e, st), add="+")
            self._visible_tabs.append((btn, tab_state))

        if hasattr(self.category_tabs_canvas, "_mousewheel_binder"):
            self.category_tabs_canvas._mousewheel_binder()

    def _tab_drag_start(self, event, tab_state):
        # Same reasoning as _row_drag_start: don't rebuild the tab strip
        # here, since that would destroy the very button holding the mouse
        # grab for this drag.
        self._dragging_tab = tab_state["cat"]
        self._dragging_tab_state = tab_state
        self._tab_moved = False
        self.root.bind("<B1-Motion>", self._tab_drag_motion)
        self.root.bind("<ButtonRelease-1>", self._tab_drag_end)

    def _tab_drag_motion(self, event):
        dragged = self._dragging_tab
        if not dragged or dragged not in self.category_order:
            return
        di = self.category_order.index(dragged)
        for pos, (btn, st) in enumerate(self._visible_tabs):
            cat = st["cat"]
            if cat in ("All", dragged):
                continue
            ci = self.category_order.index(cat)
            mid = btn.winfo_rootx() + btn.winfo_width() // 2
            if (ci < di and event.x_root < mid) or (ci > di and event.x_root > mid):
                self.category_order[di], self.category_order[ci] = self.category_order[ci], self.category_order[di]

                # Swap on-screen positions of the SAME two buttons (repack,
                # don't recreate) so the drag handle's grab survives.
                dragged_pos = next(p for p, (_, s) in enumerate(self._visible_tabs) if s is self._dragging_tab_state)
                st["cat"] = dragged
                self._dragging_tab_state["cat"] = cat
                self._visible_tabs[dragged_pos], self._visible_tabs[pos] = \
                    self._visible_tabs[pos], self._visible_tabs[dragged_pos]
                for btn2, _ in self._visible_tabs:
                    btn2.pack_forget()
                    btn2.pack(side="left", padx=(0, 4), pady=4)

                self._tab_moved = True
                return

    def _tab_drag_end(self, event):
        self.root.unbind("<B1-Motion>")
        self.root.unbind("<ButtonRelease-1>")
        moved = self._tab_moved
        clicked_cat = self._dragging_tab
        if moved:
            regex_manager.save_category_order(self.category_order)
        self._dragging_tab = None
        self._dragging_tab_state = None
        self._tab_moved = False
        if moved:
            # Real drag - just refresh so labels/highlighting match the
            # final order. Dragging never changes which tab is selected.
            self.refresh_category_tabs()
        else:
            # No reorder happened - this was a plain click, so behave like
            # clicking any other tab. select_category() already refreshes
            # the tab strip, so no separate refresh_category_tabs() call.
            self.select_category(clicked_cat)

    def refresh_regex_list(self):
        self.refresh_category_tabs()

        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self._visible_rows = []

        visible_items = [
            (idx, item) for idx, item in enumerate(self.regex_data)
            if self.current_category == "All" or item.get("category", "General") == self.current_category
        ]

        if not visible_items:
            tk.Label(self.scrollable_frame, text="No regexes in this category yet.",
                     bg=self.bg_color, fg=self.text_dim, font=self.body_font).pack(pady=20)

        for idx, item in visible_items:
            # `row_state` is a mutable holder for this row's current index.
            # Buttons below read st['idx'] at CLICK time rather than closing
            # over a frozen idx, so dragging (which reorders rows in place
            # without rebuilding them - see _row_drag_motion) can update
            # st['idx'] and every button on the row stays pointed at the
            # right item.
            row_state = {"idx": idx}
            row_outer = tk.Frame(self.scrollable_frame, bg=self.border_gold)
            row_outer.pack(fill="x", pady=(0, 6))
            row = tk.Frame(row_outer, bg=self.panel_color, pady=10, padx=8)
            row.pack(fill="x", padx=1, pady=1)
            self._visible_rows.append((row_outer, row_state))

            handle = tk.Label(row, text="⠿", bg=self.panel_color, fg=self.text_dim,
                               font=("Segoe UI", 12), cursor="fleur")
            handle.pack(side="left", padx=(0, 8))
            handle.bind("<ButtonPress-1>", lambda e, st=row_state: self._row_drag_start(e, st))

            # Buttons are packed BEFORE the text so they always reserve their
            # space first. Regexes/titles often have no whitespace to wrap
            # on (Tk's wraplength can't break mid-word), so a long enough
            # one would otherwise claim the whole row and push COPY/edit/
            # delete off it entirely - packing order is what fixes that.
            btns = tk.Frame(row, bg=self.panel_color)
            btns.pack(side="right")

            del_btn = tk.Button(
                btns, text="✕", bg=self.btn_bg, fg=self.color_stopped, relief="flat", bd=0,
                activebackground=self.color_stopped, activeforeground="white", font=("Segoe UI", 8, "bold"),
                cursor="hand2", command=lambda st=row_state: self.delete_regex(st["idx"]), width=3
            )
            del_btn.pack(side="right", padx=(3, 0))

            edit_btn = tk.Button(
                btns, text="✎", bg=self.btn_bg, fg=self.gold, relief="flat", bd=0,
                activebackground=self.btn_hover, activeforeground=self.gold_bright, font=("Segoe UI", 8, "bold"),
                cursor="hand2", command=lambda st=row_state: self.open_regex_modal("edit", st["idx"]), width=3
            )
            edit_btn.pack(side="right", padx=(3, 0))

            copy_btn = tk.Button(
                btns, text="COPY", bg=self.btn_bg, fg=self.text_color, relief="flat", bd=0,
                activebackground=self.btn_hover, activeforeground=self.gold_bright, font=("Segoe UI", 8, "bold"),
                cursor="hand2", command=lambda r=item["regex"]: self.copy_to_clipboard(r)
            )
            copy_btn.pack(side="right")

            text_frame = tk.Frame(row, bg=self.panel_color)
            text_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

            title_row = tk.Frame(text_frame, bg=self.panel_color)
            title_row.pack(fill="x")
            title_text = item["title"][:30] + "..." if len(item["title"]) > 30 else item["title"]
            tk.Label(title_row, text=title_text, bg=self.panel_color, fg=self.gold,
                     font=self.header_font, anchor="w").pack(side="left")
            if self.current_category == "All":
                tk.Label(title_row, text=item.get("category", "General"), bg=self.panel_color,
                         fg=self.text_dim, font=("Segoe UI", 7, "bold"), anchor="w").pack(side="left", padx=(8, 0))

            preview = item["regex"][:60] + "..." if len(item["regex"]) > 60 else item["regex"]
            tk.Label(text_frame, text=preview, bg=self.panel_color, fg=self.text_dim, font=self.mono_font,
                     anchor="w", justify="left", wraplength=300).pack(fill="x", anchor="w")

        if hasattr(self.canvas, "_mousewheel_binder"):
            self.canvas._mousewheel_binder()

    def _row_drag_start(self, event, row_state):
        # NOTE: deliberately does NOT call refresh_regex_list() here. The
        # handle that was just pressed holds Tk's implicit mouse grab for
        # the rest of this drag - destroying/recreating it (which a full
        # refresh does) breaks that grab and is what made dragging feel
        # broken (dropped motion events, drags that randomly stop, the
        # occasional TclError). We only touch this row's own background.
        self._dragging_idx = row_state["idx"]
        self._dragging_row_state = row_state
        self._row_moved = False
        for row_outer, st in self._visible_rows:
            if st is row_state:
                row_outer.config(bg=self.gold_bright)
                break
        self.root.bind("<B1-Motion>", self._row_drag_motion)
        self.root.bind("<ButtonRelease-1>", self._row_drag_end)

    def _row_drag_motion(self, event):
        dragged_idx = self._dragging_idx
        if dragged_idx is None:
            return
        for pos, (row_outer, st) in enumerate(self._visible_rows):
            idx = st["idx"]
            if idx == dragged_idx:
                continue
            mid = row_outer.winfo_rooty() + row_outer.winfo_height() // 2
            if (idx < dragged_idx and event.y_root < mid) or (idx > dragged_idx and event.y_root > mid):
                self.regex_data[dragged_idx], self.regex_data[idx] = self.regex_data[idx], self.regex_data[dragged_idx]

                # Re-point the two rows' idx holders at their new data
                # positions, then swap their slot in the display list and
                # repack all rows in that order. This moves the SAME frame
                # widgets around on screen - nothing is destroyed, so the
                # drag handle's grab (and the drag itself) survives.
                dragged_pos = next(p for p, (_, s) in enumerate(self._visible_rows) if s is self._dragging_row_state)
                st["idx"] = dragged_idx
                self._dragging_row_state["idx"] = idx
                self._visible_rows[dragged_pos], self._visible_rows[pos] = \
                    self._visible_rows[pos], self._visible_rows[dragged_pos]
                for row_outer2, _ in self._visible_rows:
                    row_outer2.pack_forget()
                    row_outer2.pack(fill="x", pady=(0, 6))

                self._dragging_idx = idx
                self._row_moved = True
                return

    def _row_drag_end(self, event):
        self.root.unbind("<B1-Motion>")
        self.root.unbind("<ButtonRelease-1>")
        if self._row_moved:
            regex_manager.save_regex_data(self.regex_data)
        self._dragging_idx = None
        self._dragging_row_state = None
        self._row_moved = False
        # Safe to fully rebuild now - the mouse button is up, so there's no
        # grab to break.
        self.refresh_regex_list()

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.update_status("COPIED TO CLIPBOARD", self.color_running)

    def delete_regex(self, idx):
        if 0 <= idx < len(self.regex_data):
            self.regex_data.pop(idx)
            regex_manager.save_regex_data(self.regex_data)
            self.refresh_regex_list()

    def export_regex_vault(self):
        if not self.regex_data:
            self.update_status("NOTHING TO EXPORT", self.color_stopped)
            return

        path = filedialog.asksaveasfilename(
            title="Export Regex Vault",
            defaultextension=".json",
            initialfile="regex_vault_export.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return  # user cancelled

        try:
            with open(path, 'w') as f:
                json.dump(self.regex_data, f, indent=4)
            self.update_status(f"EXPORTED {len(self.regex_data)} ENTRIES", self.color_running)
        except Exception as e:
            self.update_status(f"EXPORT FAILED: {e}", self.color_stopped)

    def import_regex_vault(self):
        path = filedialog.askopenfilename(
            title="Import Regex Vault",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return  # user cancelled

        try:
            with open(path, 'r') as f:
                imported = json.load(f)
        except Exception as e:
            self.update_status(f"IMPORT FAILED: {e}", self.color_stopped)
            return

        if not isinstance(imported, list):
            self.update_status("INVALID VAULT FILE", self.color_stopped)
            return

        # De-dupe on (title, regex) so importing the same file twice - or a
        # file that overlaps with what you already have - doesn't create copies.
        existing_keys = {(item.get("title"), item.get("regex")) for item in self.regex_data}
        added, skipped = 0, 0

        for entry in imported:
            if not isinstance(entry, dict) or not entry.get("title") or not entry.get("regex"):
                skipped += 1
                continue
            key = (entry["title"], entry["regex"])
            if key in existing_keys:
                skipped += 1
                continue
            self.regex_data.append({
                "title": entry["title"],
                "regex": entry["regex"],
                "category": entry.get("category", "General")
            })
            existing_keys.add(key)
            added += 1

        if added:
            regex_manager.save_regex_data(self.regex_data)
            self.refresh_regex_list()

        status_color = self.color_running if added else self.color_warn
        self.update_status(f"IMPORTED {added} - SKIPPED {skipped}", status_color)

    # --- Interaction Logic ---
    def toggle_mode(self):
        if config.CRAFTING_MODE == 'AUTO':
            config.CRAFTING_MODE = 'MANUAL'
            self.mode_btn.config(text="MODE: MANUAL (YOU CLICK)", fg=self.color_warn)
            self.update_status("MANUAL MODE READY", self.color_warn)
        else:
            config.CRAFTING_MODE = 'AUTO'
            self.mode_btn.config(text="MODE: FULL AUTO", fg=self.color_running)
            self.update_status("AUTO MODE READY", self.color_running)

    def _start_label(self):
        return f"START ({config.START_DELAY_SECONDS:g}s)"

    def _update_start_button_label(self):
        self.start_btn.config(text=self._start_label())

    def initiate_start(self):
        if getattr(self, "_trial_locked", False):
            self.update_status("TRIAL ENDED", self.color_stopped)
            return
        if self.crafter.is_running or self.is_starting:
            return
        if not config.SCAN_REGION or not config.SCAN_REGION_CONFIRMED:
            self.update_status("NO SCAN REGION - CLICK 'SET SCAN REGION' BELOW", self.color_stopped)
            self._update_region_hint()
            return

        self._ensure_pinned()

        self.is_starting = True
        self.countdown = int(round(config.START_DELAY_SECONDS))
        self.start_btn.config(state="disabled")
        self.process_countdown()

    def process_countdown(self):
        if self.countdown > 0 and self.is_starting:
            self._update_status_ui(f"STARTING IN {self.countdown}...", self.color_warn)
            self.countdown -= 1
            self.root.after(1000, self.process_countdown)
        elif self.is_starting:
            self.is_starting = False
            self.start_btn.config(state="normal")
            self.crafter.start()

    def cancel_start(self):
        # Lets the toggle hotkey actually cancel a queued countdown instead of no-op'ing.
        if self.is_starting:
            self.is_starting = False
            self.start_btn.config(state="normal")
            self.update_status("START CANCELLED", self.color_stopped)

    def save_intervals(self):
        try:
            min_v = float(self.min_var.get())
            max_v = float(self.max_var.get())
            if min_v <= 0 or max_v <= 0:
                self.update_status("INTERVALS MUST BE > 0", self.color_stopped)
                return
            if min_v > max_v:
                self.update_status("MIN CANNOT EXCEED MAX", self.color_stopped)
                return
            config.CLICK_INTERVAL_MIN = min_v
            config.CLICK_INTERVAL_MAX = max_v
            settings_manager.save_settings()
            self.update_status("INTERVALS SAVED", self.color_running)
        except (ValueError, tk.TclError):
            self.update_status("INVALID NUMBER", self.color_stopped)

    def _burst_label(self):
        return f"BURST MODE: {'ON' if config.BURST_MODE_ENABLED else 'OFF'}"

    def toggle_burst_mode(self):
        config.BURST_MODE_ENABLED = not config.BURST_MODE_ENABLED
        self.burst_toggle_btn.config(
            text=self._burst_label(),
            fg=self.color_running if config.BURST_MODE_ENABLED else self.text_dim
        )
        settings_manager.save_settings()
        self.update_status(
            "BURST MODE: ON" if config.BURST_MODE_ENABLED else "BURST MODE: OFF",
            self.color_running if config.BURST_MODE_ENABLED else self.text_dim
        )

    def save_click_behavior(self):
        try:
            start_delay = float(self.start_delay_var.get())
            hold_min = float(self.hold_min_var.get())
            hold_max = float(self.hold_max_var.get())
            burst_clicks_min = int(self.burst_clicks_min_var.get())
            burst_clicks_max = int(self.burst_clicks_max_var.get())
            burst_interval_min = float(self.burst_interval_min_var.get())
            burst_interval_max = float(self.burst_interval_max_var.get())
            burst_rest_min = float(self.burst_rest_min_var.get())
            burst_rest_max = float(self.burst_rest_max_var.get())
        except (ValueError, tk.TclError):
            self.update_status("INVALID NUMBER", self.color_stopped)
            return

        if start_delay < 0:
            self.update_status("START DELAY CAN'T BE NEGATIVE", self.color_stopped)
            return
        if hold_min <= 0 or hold_max <= 0 or hold_min > hold_max:
            self.update_status("CLICK HOLD RANGE INVALID", self.color_stopped)
            return
        if burst_clicks_min < 1 or burst_clicks_max < 1 or burst_clicks_min > burst_clicks_max:
            self.update_status("BURST SIZE RANGE INVALID", self.color_stopped)
            return
        if burst_interval_min <= 0 or burst_interval_max <= 0 or burst_interval_min > burst_interval_max:
            self.update_status("BURST INTERVAL RANGE INVALID", self.color_stopped)
            return
        if burst_rest_min <= 0 or burst_rest_max <= 0 or burst_rest_min > burst_rest_max:
            self.update_status("REST RANGE INVALID", self.color_stopped)
            return

        config.START_DELAY_SECONDS = start_delay
        config.CLICK_HOLD_MIN = hold_min
        config.CLICK_HOLD_MAX = hold_max
        config.BURST_CLICKS_MIN = burst_clicks_min
        config.BURST_CLICKS_MAX = burst_clicks_max
        config.BURST_INTERVAL_MIN = burst_interval_min
        config.BURST_INTERVAL_MAX = burst_interval_max
        config.BURST_REST_MIN = burst_rest_min
        config.BURST_REST_MAX = burst_rest_max
        settings_manager.save_settings()
        self._update_start_button_label()
        self.update_status("CLICK BEHAVIOR SAVED", self.color_running)

    # --- First-run guidance --------------------------------------------
    def _update_region_hint(self):
        if not config.SCAN_REGION or not config.SCAN_REGION_CONFIRMED:
            self.region_hint_var.set("⚠ Set your Scan Region below before starting")
        else:
            self.region_hint_var.set("")

    # --- Craft counter ---------------------------------------------------
    @staticmethod
    def _fmt_duration(seconds):
        seconds = max(0, int(seconds))
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _tick_stats(self):
        if self.crafter.is_running and self.crafter.start_time is not None:
            elapsed = time.time() - self.crafter.start_time
            self.stats_var.set(
                f"Clicks: {self.crafter.click_count}   ·   Time: {self._fmt_duration(elapsed)}"
            )
        elif self.crafter.last_run_clicks or self.crafter.last_run_seconds:
            self.stats_var.set(
                f"Last run: {self.crafter.last_run_clicks} clicks in "
                f"{self._fmt_duration(self.crafter.last_run_seconds)}"
            )
        else:
            self.stats_var.set("")
        self.root.after(500, self._tick_stats)

    # --- Hotkeys -----------------------------------------------------------
    def _update_hotkey_info(self):
        self.hotkey_info_var.set(
            f"Toggle: {config.TOGGLE_HOTKEY.upper()}  |  "
            f"Overlay: {config.OVERLAY_HOTKEY.upper()}  |  "
            f"Exit: {config.EXIT_HOTKEY.upper()}"
        )

    def run_hotkey_editor(self):
        from hotkey_editor import HotkeyEditor
        self._pause_hotkeys()
        theme = {
            "bg": self.bg_color, "panel": self.panel_color, "border": self.border_gold,
            "gold": self.gold, "text": self.text_color, "text_dim": self.text_dim,
            "btn_bg": self.btn_bg, "ok": self.color_running, "bad": self.color_stopped,
        }
        HotkeyEditor(
            self.root,
            on_saved=self._on_hotkeys_saved,
            on_closed=self._resume_hotkeys_if_crafter,
            theme=theme,
        )

    def _on_hotkeys_saved(self):
        self._update_hotkey_info()
        self.update_status("HOTKEYS SAVED", self.color_running)

    def run_region_finder(self):
        self.show_tab('crafter')

        def routine():
            self.update_status("Move mouse to TOP-LEFT...", self.color_warn)
            time.sleep(3)
            x1, y1 = pyautogui.position()

            self.update_status("Move mouse to BOTTOM-RIGHT...", self.color_warn)
            time.sleep(3)
            x2, y2 = pyautogui.position()

            w, h = abs(x2 - x1), abs(y2 - y1)
            if w < 4 or h < 4:
                self.update_status("REGION TOO SMALL - TRY AGAIN", self.color_stopped)
                return

            config.SCAN_REGION = (min(x1, x2), min(y1, y2), w, h)
            config.SCAN_REGION_CONFIRMED = True
            settings_manager.save_settings()
            self.update_status("REGION SAVED", self.color_running)
            self.root.after(0, self._update_region_hint)

            if self.overlay.is_showing:
                self.overlay.hide()
                self.overlay.show()

        threading.Thread(target=routine, daemon=True).start()

    def run_calibrator(self):
        if not config.SCAN_REGION:
            self.update_status("NO SCAN REGION - CLICK 'SET SCAN REGION' ABOVE", self.color_stopped)
            return
        from calibrator import ClickCalibrator
        self._pause_hotkeys()

        def on_saved():
            self._update_region_hint()
            self.update_status("COLOR CALIBRATED", self.color_running)

        ClickCalibrator(
            self.root,
            on_saved=on_saved,
            on_advanced=self.run_hsv_tuner,
            on_closed=self._resume_hotkeys_if_crafter
        )

    def run_hsv_tuner(self):
        if not config.SCAN_REGION:
            self.update_status("NO SCAN REGION - CLICK 'SET SCAN REGION' ABOVE", self.color_stopped)
            return
        from hsv_tuner import HSVTuner
        self._pause_hotkeys()
        theme = {
            "bg": self.bg_color, "panel": self.panel_color, "border": self.border_gold,
            "gold": self.gold, "text": self.text_color, "text_dim": self.text_dim,
            "btn_bg": self.btn_bg, "ok": self.color_running, "bad": self.color_stopped,
        }

        def on_status(text, color):
            if text == "HSV SAVED":
                self._update_region_hint()
            self.update_status(text, color)

        tuner = HSVTuner.open(
            self.root,
            on_status=on_status,
            theme=theme,
        )
        tuner.win.bind("<Destroy>", lambda e: self._resume_hotkeys_if_crafter(), add="+")
        self.update_status("TUNING HSV LIVE", self.color_found)

    def _pause_hotkeys(self):
        if not self._hotkeys_registered:
            return
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self._hotkeys_registered = False

    def _resume_hotkeys(self):
        if self._hotkeys_registered:
            return
        self.register_hotkeys()

    def _resume_hotkeys_if_crafter(self):
        if self.crafter_frame.winfo_ismapped():
            self._resume_hotkeys()

    def register_hotkeys(self):
        # NOTE: previously both e.g. 'f4' and 'shift+f4' were bound to the same
        # action. The `keyboard` library fires a plain-key hotkey regardless of
        # what modifiers are held, so Shift+F4 fired BOTH bindings and the
        # toggle flipped twice (looked like nothing happened). Bound once each.
        # Callbacks are also marshalled onto the Tk main thread via root.after,
        # since `keyboard` invokes them on its own internal thread.
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        def toggle_crafting():
            self.root.after(0, self._toggle_crafting_safe)

        def toggle_overlay():
            self.root.after(0, self.overlay.toggle)

        keyboard.add_hotkey(config.TOGGLE_HOTKEY, toggle_crafting)
        keyboard.add_hotkey(config.OVERLAY_HOTKEY, toggle_overlay)
        self._hotkeys_registered = True

    def _toggle_crafting_safe(self):
        if getattr(self, "_trial_locked", False):
            self.update_status("TRIAL ENDED", self.color_stopped)
            return
        if self.crafter.is_running:
            self.crafter.stop()
        elif self.is_starting:
            self.cancel_start()
        else:
            self.initiate_start()

    def minimize_to_tray(self):
        if self._tray is None:
            self.root.iconify()
            return
        try:
            self.root.withdraw()
        except tk.TclError:
            pass

    def restore_from_tray(self, icon=None, item=None):
        self.root.after(0, self._restore_from_tray_ui)

    def _restore_from_tray_ui(self):
        try:
            self.root.deiconify()
            # Restoring from the tray should behave like clicking any other
            # app's taskbar icon - it comes to the very front immediately,
            # regardless of the Pin setting. A bare lift()/deiconify() isn't
            # reliably enough to beat whatever window currently has focus
            # (especially another always-on-top window, or a fullscreen
            # game), so momentarily force -topmost + input focus here, then
            # settle back to the user's actual Pin choice a moment later
            # instead of leaving it permanently pinned when they had Pin
            # turned off - deiconify() can drop -topmost on Windows anyway,
            # and the old code re-applied config.ALWAYS_ON_TOP immediately,
            # which meant a non-pinned window only got a plain lift() and
            # could stay stuck behind whatever already had focus.
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(50, self.root.lift)
            self.root.after(200, self._settle_topmost_after_restore)
        except tk.TclError:
            pass

    def _settle_topmost_after_restore(self):
        try:
            self.root.attributes("-topmost", config.ALWAYS_ON_TOP)
        except tk.TclError:
            pass

    def _tray_close(self, icon=None, item=None):
        self.root.after(0, self.close_app)

    def _tray_icon_image(self):
        import app_icon
        return app_icon.get_tray_image()

    def _set_window_icon(self):
        """Same gold diamond as the tray icon (app_icon.py) - without this,
        an overrideredirect window still falls back to Tk's default icon
        in the taskbar/Alt-Tab, which is why it used to look like a
        different app from what showed up in the tray. `default=True`
        also applies it to Toplevels spawned from this root (HSV tuner,
        hotkey editor, calibrator, ...) that don't set their own icon."""
        import app_icon
        self._icon_photo = app_icon.get_photo_image()  # keep a ref - Tk drops GC'd images
        try:
            self.root.iconphoto(True, self._icon_photo)
        except tk.TclError:
            pass

    def _start_tray(self):
        try:
            import pystray
        except Exception as e:
            # Used to be `except ImportError: return` - silent, with zero
            # clue why the tray never showed up. That's exactly the failure
            # mode a onefile PyInstaller build hits: `python main.pyw` has
            # the full site-packages on disk, but the frozen exe only has
            # whatever PyInstaller's static analysis managed to bundle, so
            # this can raise there even though it never did from source.
            # Logged so it lands in crafter_log.txt on windowed/no-console
            # builds (see main.pyw's stdout/stderr redirect) instead of
            # just disappearing without a trace.
            print(f"[!] Tray icon disabled - could not import pystray: {e}")
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Open", self.restore_from_tray, default=True),
                pystray.MenuItem("Close", self._tray_close),
            )
            self._tray = pystray.Icon("AutoCrafter", self._tray_icon_image(), "Auto-Crafter", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception as e:
            print(f"[!] Tray icon disabled - failed to start: {e}")
            self._tray = None

    def on_close(self):
        self.minimize_to_tray()

    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        self.crafter.stop()
        self.crafter.release_keys()
        self.overlay.hide()
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        tray = self._tray
        self._tray = None
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()