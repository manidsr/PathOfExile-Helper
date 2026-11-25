# app_icon.py
#
# Loads the app's real icon - config.APP_ICON_FILE, i.e. app_icon.ico
# sitting next to config.py/main.pyw (or bundled via PyInstaller's
# datas=[...] once frozen, same as TARGET_IMAGE) - and hands it out in
# whatever form each consumer needs:
#   - a PIL Image for the tray icon (pystray.Icon(...) wants a PIL Image)
#   - a Tk PhotoImage for root.iconphoto() - the actual window icon
#     (taskbar / Alt-Tab), used by both LicenseGate and CrafterGUI
#
# Previously this module drew a placeholder gold diamond in code instead
# of reading any file, which is why dropping a real icon into the project
# folder had no effect - nothing here ever looked at disk. It now reads
# config.APP_ICON_FILE; the diamond only survives as a fallback so a
# missing/renamed file doesn't crash the app before you've placed it.

from PIL import Image, ImageTk
import config


def _load_pil_image():
    """The user's real icon, loaded fresh each call (cheap - it's a small
    file) so replacing app_icon.ico and restarting the app picks up the
    change without any other code needing to know about it."""
    try:
        return Image.open(config.APP_ICON_FILE).convert("RGBA")
    except Exception:
        return _fallback_icon()


def _fallback_icon(size=64):
    """Only used if config.APP_ICON_FILE is missing/unreadable - e.g. it
    hasn't been placed next to config.py yet, or a frozen build forgot to
    list it in the .spec's datas=[...]."""
    from PIL import ImageDraw
    img = Image.new("RGBA", (size, size), (21, 19, 15, 255))
    draw = ImageDraw.Draw(img)
    pad = max(2, size // 10)
    draw.polygon(
        [(size // 2, pad), (size - pad, size // 2), (size // 2, size - pad), (pad, size // 2)],
        fill=(200, 170, 110, 255),
    )
    return img


def get_tray_image():
    """PIL Image for pystray.Icon(...)."""
    return _load_pil_image()


def get_photo_image():
    """Tk PhotoImage for root.iconphoto() - the in-app window icon. Keep a
    reference to the returned object for as long as the window is open;
    Tk silently drops the icon if the PhotoImage gets garbage collected."""
    return ImageTk.PhotoImage(_load_pil_image())
