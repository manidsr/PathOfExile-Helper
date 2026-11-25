import sys
import tkinter as tk
import config
from dpi_utils import enable_dpi_awareness
from desktop import Desktop

if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(config.data_file("helper.log"), "a", encoding="utf-8", buffering=1)
    enable_dpi_awareness()
    root = tk.Tk()
    Desktop(root)
    root.mainloop()
