import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import config
import sender

BG, PANEL, FIELD, EDGE = "#12161C", "#1C222A", "#151B21", "#37424C"
INK, MUTED, MINT = "#F0F4F5", "#A4B1BC", "#80DDC0"
FONT = "Segoe UI"


def label(parent, text, size=10, color=INK, bold=False):
    return tk.Label(parent, text=text, bg=parent["bg"], fg=color, anchor="w",
                    font=(FONT, size, "bold" if bold else "normal"))


def button(parent, text, action, primary=False):
    return tk.Button(parent, text=text, command=action, cursor="hand2", bd=0,
                     relief="flat", highlightthickness=0, padx=14, pady=8,
                     font=(FONT, 10, "bold"), bg=MINT if primary else "#2B3640",
                     fg=BG if primary else INK, activebackground="#A9EED7", activeforeground=BG)


def field(parent, title, variable, secret=False):
    label(parent, title, 10, MUTED).pack(fill="x", pady=(12, 5))
    entry = tk.Entry(parent, textvariable=variable, bg=FIELD, fg=INK, relief="flat",
                     highlightthickness=1, highlightbackground=EDGE, highlightcolor=MINT,
                     insertbackground=MINT, font=(FONT, 11), show="•" if secret else "")
    entry.pack(fill="x", ipady=7)
    return entry


class Desktop:
    def __init__(self, root):
        self.root = root
        root.title("Path of Exile Helper")
        root.configure(bg=BG)
        root.geometry("920x650")
        root.minsize(730, 560)
        if os.name == "nt":
            root.iconbitmap(config.APP_ICON_FILE)
        self.crafter = self.gate = self.worker = None
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.draft = Path(config.DATA_DIR) / "sender-draft.json"
        try:
            saved = json.loads(self.draft.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        self.channel = tk.StringVar(value=saved.get("channel", ""))
        self.token = tk.StringVar(value=os.getenv("POE_SENDER_BOT_TOKEN", ""))
        self.interval = tk.StringVar(value=saved.get("minutes", "60"))
        self.repeat = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready")
        bar = tk.Frame(root, bg=PANEL, padx=20, pady=10)
        bar.pack(fill="x")
        label(bar, "◆", 15, MINT).pack(side="left", padx=(0, 8))
        label(bar, "Path of Exile Helper", 14, bold=True).pack(side="left")
        self.nav = {}
        for name in ("Auto Crafter", "Auto Sender"):
            btn = button(bar, name, lambda key=name: self.show(key))
            btn.pack(side="right", padx=3)
            self.nav[name] = btn
        self.pages = {name: tk.Frame(root, bg=BG) for name in self.nav}
        self.build_sender(self.pages["Auto Sender"], saved.get("message", ""))
        self.locked = tk.Frame(self.pages["Auto Crafter"], bg=PANEL, padx=22, pady=22)
        self.locked.pack(fill="x", padx=24, pady=24)
        label(self.locked, "Auto Crafter", 24, bold=True).pack(fill="x")
        label(self.locked, "Activate your license to open crafting controls, calibration and the regex vault.",
              11, MUTED).pack(fill="x", pady=(6, 18))
        button(self.locked, "Open crafter", self.activate, True).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.show("Auto Sender")
        root.after(150, self.poll)

    def show(self, name):
        if self.crafter:
            if name == "Auto Sender":
                self.crafter.cancel_start()
                self.crafter.crafter.stop()
                self.crafter._pause_hotkeys()
                self.crafter.overlay.hide()
                self.root.attributes("-topmost", False)
            else:
                self.root.attributes("-topmost", config.ALWAYS_ON_TOP)
                self.crafter.show_tab(self.crafter.active_tab)
        for key, page in self.pages.items():
            page.pack_forget()
            self.nav[key].configure(bg=MINT if key == name else PANEL, fg=BG if key == name else MUTED)
        self.pages[name].pack(fill="both", expand=True)

    def activate(self):
        from license_gate import LicenseGate
        if self.gate and self.gate.root.winfo_exists():
            self.gate.root.lift()
            return
        self.gate = LicenseGate(self.root, self.open_crafter)

    def open_crafter(self):
        try:
            from gui import CrafterGUI
            self.crafter = CrafterGUI(self.root, self.pages["Auto Crafter"], self.close)
        except (ImportError, OSError) as error:
            messagebox.showerror("Auto Crafter", str(error), parent=self.root)
            return
        self.locked.destroy()
        self.show("Auto Crafter")

    def build_sender(self, page, draft):
        body = tk.Frame(page, bg=BG, padx=24, pady=18)
        body.pack(fill="both", expand=True)
        label(body, "Auto Sender", 24, bold=True).pack(fill="x", pady=(0, 14))
        columns = tk.Frame(body, bg=BG)
        columns.pack(fill="both", expand=True)
        options = tk.Frame(columns, bg=PANEL, width=255, padx=16, pady=16)
        options.pack(side="right", fill="y", padx=(14, 0))
        label(options, "Delivery", 14, bold=True).pack(fill="x")
        self.inputs = [field(options, "Channel ID", self.channel),
                       field(options, "Bot token", self.token, secret=True)]
        toggle = tk.Checkbutton(options, text="Repeat message", variable=self.repeat,
                                command=self.sync, fg=INK, bg=PANEL, selectcolor=FIELD,
                                activebackground=PANEL, activeforeground=INK, font=(FONT, 10))
        toggle.pack(anchor="w", pady=(18, 0))
        self.inputs.append(toggle)
        self.minutes = field(options, "Interval in minutes", self.interval)
        edit = tk.Frame(columns, bg=PANEL, padx=16, pady=16)
        edit.pack(fill="both", expand=True)
        row = tk.Frame(edit, bg=PANEL)
        row.pack(fill="x", pady=(0, 10))
        label(row, "Message", 14, bold=True).pack(side="left")
        self.import_btn = button(row, "Import .txt", self.import_text)
        self.import_btn.pack(side="right")
        self.editor = tk.Text(edit, wrap="word", undo=True, width=1, height=4, relief="flat",
                              font=(FONT, 12), bg=FIELD, fg=INK, insertbackground=MINT,
                              selectbackground="#37685D", padx=14, pady=14, spacing1=2, spacing3=4,
                              highlightthickness=1, highlightcolor=MINT, highlightbackground=EDGE)
        self.editor.pack(fill="both", expand=True)
        self.counter = label(edit, "", 9, MUTED)
        self.counter.pack(anchor="e", pady=(6, 0))
        self.editor.insert("1.0", draft)
        self.editor.bind("<<Modified>>", self.count)
        self.count()
        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", pady=(14, 0))
        self.send = button(footer, "Send message", self.start, True)
        self.send.pack(side="right", padx=(10, 0))
        self.cancel = button(footer, "Stop", self.cancel_send)
        self.cancel.pack(side="right")
        tk.Label(footer, textvariable=self.status, bg=BG, fg=MUTED, font=(FONT, 10),
                 wraplength=420, justify="left").pack(side="left")
        self.sync()

    def message(self):
        return self.editor.get("1.0", "end-1c")

    def count(self, event=None):
        length = len(self.message())
        self.counter.configure(text=f"{length:,} / 2,000", fg=MUTED if length <= 2000 else "#FF938D")
        self.editor.edit_modified(False)

    def import_text(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                self.status.set("Could not read this file. Choose a UTF-8 text file.")
                return
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", text)

    def sync(self):
        busy = self.worker is not None
        state = "disabled" if busy else "normal"
        for widget in [*self.inputs, self.import_btn, self.editor, self.send]:
            widget.configure(state=state)
        self.minutes.configure(state="normal" if self.repeat.get() and not busy else "disabled")
        self.send.configure(text="Start schedule" if self.repeat.get() else "Send message")
        self.cancel.configure(state="normal" if busy and not self.stop.is_set() else "disabled")

    def save(self):
        data = dict(message=self.message(), channel=self.channel.get(), minutes=self.interval.get())
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.draft.parent, delete=False) as out:
            json.dump(data, out, ensure_ascii=False)
        os.replace(out.name, self.draft)

    def start(self):
        if self.worker:
            return
        args = (self.channel.get().strip(), self.token.get().strip(), self.message(),
                self.interval.get().strip() if self.repeat.get() else "1")
        try:
            sender.validate(*args)
            self.save()
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        self.stop.clear()
        self.status.set("Sending…")
        self.worker = threading.Thread(target=sender.run, args=(*args, self.repeat.get(), self.stop,
                                                               self.events.put), daemon=True)
        self.worker.start()
        self.sync()

    def cancel_send(self):
        self.stop.set()
        self.status.set("Stopping…")
        self.sync()

    def poll(self):
        finished = self.worker and not self.worker.is_alive()
        while not self.events.empty():
            self.status.set(self.events.get_nowait())
        if finished:
            self.worker = None
            if self.stop.is_set():
                self.status.set("Stopped")
            self.sync()
        self.root.after(150, self.poll)

    def close(self):
        try:
            self.save()
        except OSError as error:
            if not messagebox.askyesno("Draft could not be saved", f"{error}\nClose anyway?"):
                return
        self.stop.set()
        if self.crafter:
            self.crafter.quit_app()
        else:
            self.root.destroy()
