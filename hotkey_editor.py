# hotkey_editor.py
#
# Lets the user rebind the three global hotkeys (toggle crafting, toggle
# overlay, panic exit) instead of being stuck with the hardcoded F4/F5/Esc.
# Esc in particular is a bad forced default for a panic key - it collides
# with closing menus, dropdowns, and other overlays while typing.
#
# Capture uses keyboard.read_hotkey() (blocking) on a worker thread rather
# than binding Tk <KeyPress>, for two reasons: it's a global capture (works
# even though this window doesn't have OS focus priority the way a game
# does), and it already returns combos in the exact string format
# keyboard.add_hotkey() expects, modifiers included, with no keysym mapping
# to get wrong.

import threading
import tkinter as tk
import keyboard

import config
import settings_manager
import ui_utils

# (internal key, display label, config attribute name)
ACTIONS = [
    ("toggle", "Toggle Crafting", "TOGGLE_HOTKEY"),
    ("overlay", "Toggle Overlay", "OVERLAY_HOTKEY"),
    ("exit", "Panic Exit", "EXIT_HOTKEY"),
]
DEFAULTS = {"toggle": "f4", "overlay": "f5", "exit": "esc"}
_LABELS = {key: label for key, label, _ in ACTIONS}


class HotkeyEditor:
    def __init__(self, parent, on_saved=None, on_closed=None, theme=None):
        self.parent = parent
        self.on_saved = on_saved
        self.on_closed = on_closed
        self._listening = False

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

        self.pending = {
            "toggle": config.TOGGLE_HOTKEY,
            "overlay": config.OVERLAY_HOTKEY,
            "exit": config.EXIT_HOTKEY,
        }

        self.win = tk.Toplevel(parent)
        self.win.configure(bg=self.bg)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        ui_utils.add_title_strip(
            self.win, self.win, "HOTKEYS",
            bg=self.bg, panel_bg=self.panel, fg=self.gold, fg_dim=self.text_dim,
            close_command=self._cancel
        )
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)
        self.win.bind("<Destroy>", lambda e: self._on_destroy(), add="+")

        body = tk.Frame(self.win, bg=self.bg, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Click Change, then press the key (or combo) you want.")
        tk.Label(
            body, textvariable=self.status_var, bg=self.bg, fg=self.text,
            font=("Segoe UI", 9), wraplength=300, justify="left"
        ).pack(anchor="w", pady=(0, 10))

        self.key_vars = {}
        self.change_btns = {}
        for key, label, _attr in ACTIONS:
            row = tk.Frame(body, bg=self.bg)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label, bg=self.bg, fg=self.text, font=("Segoe UI", 9),
                     width=15, anchor="w").pack(side="left")
            var = tk.StringVar(value=self.pending[key].upper())
            self.key_vars[key] = var
            tk.Label(row, textvariable=var, bg=self.btn_bg, fg=self.gold,
                     font=("Consolas", 9, "bold"), width=12, anchor="center").pack(side="left", padx=(4, 8))
            btn = tk.Button(
                row, text="Change", command=lambda k=key: self._start_capture(k),
                bg=self.btn_bg, fg=self.gold, relief="flat", padx=8, pady=3, cursor="hand2"
            )
            btn.pack(side="left")
            self.change_btns[key] = btn

        tk.Label(
            body,
            text="Panic Exit is your emergency stop - pick something you won't hit by "
                 "accident while typing or alt-tabbing.",
            bg=self.bg, fg=self.text_dim, font=("Segoe UI", 8), wraplength=300, justify="left"
        ).pack(anchor="w", pady=(8, 10))

        btn_row = tk.Frame(body, bg=self.bg)
        btn_row.pack(fill="x")
        tk.Button(
            btn_row, text="Defaults", command=self._restore_defaults,
            bg=self.btn_bg, fg=self.text_dim, relief="flat", padx=10, pady=6, cursor="hand2"
        ).pack(side="left")
        tk.Button(
            btn_row, text="Save", command=self._save,
            bg=self.btn_bg, fg=self.ok, relief="flat", padx=12, pady=6, cursor="hand2"
        ).pack(side="right")
        tk.Button(
            btn_row, text="Cancel", command=self._cancel,
            bg=self.btn_bg, fg=self.bad, relief="flat", padx=12, pady=6, cursor="hand2"
        ).pack(side="right", padx=(0, 8))

        ui_utils.finalize_toplevel(self.win, parent=parent)

    def _set_buttons_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in self.change_btns.values():
            btn.config(state=state)

    def _start_capture(self, key):
        if self._listening:
            return
        self._listening = True
        self._set_buttons_enabled(False)
        self.status_var.set(f"Listening... press the key (or combo) for '{_LABELS[key]}'.")

        def worker():
            try:
                combo = self._capture_single_combo()
            except Exception:
                combo = None
            try:
                self.win.after(0, self._capture_done, key, combo)
            except tk.TclError:
                pass  # window closed while we were waiting on a keypress

        threading.Thread(target=worker, daemon=True).start()

    # Some laptop keyboards have no physical F-row and send a synthetic
    # Fn-combo as TWO separate key codes at once (e.g. Fn+5 -> both 'f5'
    # and '5' land as key-down events almost simultaneously). Plain
    # keyboard.read_hotkey() has no concept of "this second key is just
    # noise" and merges everything currently held into a "+"-joined combo,
    # so a single physical press got recorded as "5+f5" - a hotkey that
    # then required holding two full keys at once instead of just Fn+5.
    #
    # Fix: track modifier keys (ctrl/shift/alt/win) normally, but for the
    # "main" key only keep the FIRST non-modifier key-down seen and ignore
    # any further ones (the phantom duplicate) until every key involved is
    # released. This still supports real combos like "ctrl+f5".
    _MODIFIER_NAMES = {
        'ctrl', 'left ctrl', 'right ctrl',
        'shift', 'left shift', 'right shift',
        'alt', 'left alt', 'right alt',
        'windows', 'left windows', 'right windows',
    }

    def _capture_single_combo(self):
        modifiers = []
        main_key = None
        held = set()
        while True:
            event = keyboard.read_event(suppress=True)
            name = (event.name or '').lower()
            if not name:
                continue
            if event.event_type == keyboard.KEY_DOWN:
                held.add(name)
                if name in self._MODIFIER_NAMES:
                    if name not in modifiers:
                        modifiers.append(name)
                elif main_key is None:
                    main_key = name  # first real key wins; later duplicates ignored
            elif event.event_type == keyboard.KEY_UP:
                held.discard(name)
                if not held:
                    break
        if main_key is None:
            return None
        return '+'.join(modifiers + [main_key])

    def _capture_done(self, key, combo):
        if not self.win.winfo_exists():
            return
        self._listening = False
        self._set_buttons_enabled(True)
        if not combo:
            self.status_var.set("Couldn't read that key - try again.")
            return
        combo = combo.lower()
        conflicts = [k for k, v in self.pending.items() if k != key and v == combo]
        if conflicts:
            self.status_var.set(
                f"'{combo}' is already bound to '{_LABELS[conflicts[0]]}'. Pick a different key."
            )
            return
        self.pending[key] = combo
        self.key_vars[key].set(combo.upper())
        self.status_var.set("Click Change to rebind another, or Save.")

    def _restore_defaults(self):
        if self._listening:
            return
        for key, default in DEFAULTS.items():
            self.pending[key] = default
            self.key_vars[key].set(default.upper())
        self.status_var.set("Restored defaults. Click Save to apply.")

    def _save(self):
        if self._listening:
            return
        config.TOGGLE_HOTKEY = self.pending["toggle"]
        config.OVERLAY_HOTKEY = self.pending["overlay"]
        config.EXIT_HOTKEY = self.pending["exit"]
        settings_manager.save_settings()
        callback = self.on_saved
        self.win.destroy()
        if callback:
            callback()

    def _cancel(self):
        if self._listening:
            return
        self.win.destroy()

    def _on_destroy(self):
        if self.on_closed:
            self.on_closed()