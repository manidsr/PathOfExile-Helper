# overlay.py
import tkinter as tk
import threading
import config

class RegionOverlay:
    def __init__(self):
        self.root = None
        self.thread = None
        self.is_showing = False

    def _run_overlay(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "white")
        self.root.config(bg="white")
        
        if not config.SCAN_REGION:
            return

        x, y, w, h = config.SCAN_REGION
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        canvas = tk.Canvas(self.root, width=w, height=h, bg="white", highlightthickness=0)
        canvas.pack()
        canvas.create_rectangle(0, 0, w-1, h-1, outline="#00FF00", width=3)
        self.root.mainloop()

    def toggle(self):
        if not config.SCAN_REGION: return
        self.hide() if self.is_showing else self.show()

    def show(self):
        if not self.is_showing and config.SCAN_REGION:
            self.is_showing = True
            self.thread = threading.Thread(target=self._run_overlay, daemon=True)
            self.thread.start()

    def hide(self):
        if self.is_showing and self.root:
            self.is_showing = False
            self.root.after(0, self.root.destroy)
            self.root = None