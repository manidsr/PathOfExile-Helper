# license_gate.py
import threading
import tkinter as tk
import license_manager
import ui_utils


class LicenseGate:
    """Small activation window shown before the crafter GUI launches.
    Calls on_success() once a valid license is confirmed."""

    def __init__(self, parent, on_success):
        self.on_success = on_success
        self._checking = False
        self.root = tk.Toplevel(parent)
        self.root.transient(parent)
        self.root.title("Auto-Crafter - Activation")
        self._set_window_icon()
        self.root.configure(bg="#12161C")
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        ui_utils.add_title_strip(
            self.root, self.root, "LICENSE ACTIVATION",
            bg="#12161C", panel_bg="#1C222A", fg="#80DDC0", fg_dim="#A4B1BC",
            close_command=self.root.destroy
        )

        tk.Label(
            self.root, text="Enter your license or trial key:", bg="#12161C", fg="#F0F4F5",
            font=("Segoe UI", 9)
        ).pack(pady=(12, 4))

        self.entry = tk.Entry(
            self.root, width=32, font=("Consolas", 10), justify="center",
            bg="#29343E", fg="#F0F4F5", relief="flat", insertbackground="#80DDC0",
            highlightthickness=1, highlightbackground="#37424C"
        )
        self.entry.pack(pady=4, ipady=4)

        self.status = tk.StringVar(value="Starting...")
        tk.Label(
            self.root, textvariable=self.status, bg="#12161C", fg="#F0F4F5",
            font=("Segoe UI", 9), wraplength=320, justify="center"
        ).pack(pady=8)

        btn_row = tk.Frame(self.root, bg="#12161C")
        btn_row.pack(fill="x", padx=20, pady=(0, 12))

        self.btn = tk.Button(
            btn_row, text="Activate", command=self._activate,
            bg="#29343E", fg="#80DDC0", relief="flat", bd=0, padx=14, pady=6,
            activebackground="#394953", activeforeground="#AFF6DF", cursor="hand2"
        )
        self.btn.pack(side="left", expand=True, fill="x")

        self.entry.bind("<Return>", lambda e: self._activate())

        ui_utils.finalize_toplevel(self.root, parent)
        self.root.grab_set()

        # Show the window immediately; verify the saved license in the background
        # so startup doesn't block on Discord while the exe is still unpacking.
        self.root.after(50, self._try_saved_license_async)

    def _set_window_icon(self):
        """Same gold diamond used for the tray icon and the main GUI
        window (see app_icon.py) - this is a separate Tk() root from
        CrafterGUI's, created and destroyed before it, so it needs its
        own icon set independently."""
        import app_icon
        self._icon_photo = app_icon.get_photo_image()  # keep a ref - Tk drops GC'd images
        try:
            self.root.iconphoto(True, self._icon_photo)
        except tk.TclError:
            pass

    def _set_busy(self, busy, message):
        state = "disabled" if busy else "normal"
        self.btn.config(state=state)
        self.status.set(message)

    def _try_saved_license_async(self):
        if self._checking:
            return
        self._checking = True
        self._set_busy(True, "Checking saved license...")

        def worker():
            ok, msg = license_manager.verify_saved_license()
            self.root.after(0, self._on_saved_check_done, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_saved_check_done(self, ok, msg):
        self._checking = False
        if ok:
            self.root.destroy()
            self.on_success()
        else:
            self._set_busy(False, msg if msg != "No saved license." else "Enter your license key or trial key.")

    def _activate(self):
        if self._checking:
            return
        self._checking = True
        key = self.entry.get()
        self._set_busy(True, "Verifying...")

        def worker():
            ok, msg = license_manager.redeem_key(key)
            self.root.after(0, self._on_activate_done, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_activate_done(self, ok, msg):
        self._checking = False
        if ok:
            self.root.destroy()
            self.on_success()
        else:
            self._set_busy(False, msg)

    def run(self):
        self.root.mainloop()
