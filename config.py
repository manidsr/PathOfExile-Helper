# config.py
import os
import sys
import shutil

APP_NAME = 'AutoCrafter'

# --- Path setup -------------------------------------------------------
#
# A onefile PyInstaller exe does NOT run "in place". At launch it silently
# unpacks itself into a fresh temp folder (sys._MEIPASS) and __file__
# resolves there while running; that folder is deleted again when the app
# closes. Anything saved next to __file__ (license, settings, regex presets,
# category order) was therefore being written into a folder that no longer
# exists the next time the app starts - looking "lost" every launch.
#
# Fix: split "where bundled read-only resources live" from "where the app's
# own writable data lives", and put the writable data somewhere that
# actually persists across runs.

if getattr(sys, 'frozen', False):
    # Running as a compiled exe.
    APP_DIR = os.path.dirname(sys.executable)          # folder the .exe itself sits in
    RESOURCE_DIR = getattr(sys, '_MEIPASS', APP_DIR)   # bundled assets, onefile temp extraction dir
else:
    # Running from source (python main.pyw).
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = APP_DIR

BASE_DIR = RESOURCE_DIR  # kept for backwards compatibility with any other reads of config.BASE_DIR


def _get_data_dir():
    """Per-user writable folder that survives app restarts and onefile's
    temp-extraction-on-every-launch. Standard OS convention for small app
    config/data (what installers use, hidden by default, no OneDrive sync
    surprises like Documents would have)."""
    if sys.platform == 'win32':
        root = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        root = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        root = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    path = os.path.join(root, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = _get_data_dir()


def data_file(filename):
    """Resolve `filename` to a path inside DATA_DIR, one-time-migrating a
    same-named file from APP_DIR if the user has one there from an older
    version of the app (e.g. ran from source before, or used an older
    onefile build that happened to write next to the exe) and nothing has
    been saved to the new location yet."""
    new_path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(new_path):
        legacy_path = os.path.join(APP_DIR, filename)
        if os.path.exists(legacy_path):
            try:
                shutil.copy2(legacy_path, new_path)
            except Exception:
                pass
    return new_path


def resource_file(filename):
    """Resolve `filename` to a path inside RESOURCE_DIR - for bundled,
    read-only assets shipped with the app (not user data). Only meaningful
    for files actually included via the .spec's `datas=[...]`."""
    return os.path.join(RESOURCE_DIR, filename)


REGEX_FILE = data_file('regex_data.json')
CATEGORY_ORDER_FILE = data_file('category_order.json')
TARGET_IMAGE = resource_file('image_8de43c.png')

# App icon (.ico), used for the tray icon and the taskbar/Alt-Tab window
# icon (see app_icon.py). Bundled read-only asset, same as TARGET_IMAGE
# above - if you're building with PyInstaller, add it to the .spec's
# datas=[...] the same way image_8de43c.png is already listed there, or it
# won't exist at RESOURCE_DIR once frozen.
APP_ICON_FILE = resource_file('app_icon.ico')

# Persisted tuning data (scan region / HSV thresholds / match %) written by
# settings_manager.save_settings(). The values below are only the defaults
# used the very first time the app runs, before anything has been tuned/saved.
SETTINGS_FILE = data_file('settings.json')

# Hotkeys (rebindable in-app via "Rebind Hotkeys"; these are just the
# first-run defaults - settings_manager overwrites them from settings.json
# once the user has changed anything)
TOGGLE_HOTKEY = 'f4'
OVERLAY_HOTKEY = 'f5'
EXIT_HOTKEY = 'esc'

# Keep the app window on top of everything else. Right for actively
# crafting, annoying when tabbing out to browse/vault-manage - toggled from
# the pin button in the title bar and persisted by settings_manager.
ALWAYS_ON_TOP = True

# Seconds the GUI counts down after pressing Start before crafting actually
# begins (time to alt-tab back / get your hands positioned). Editable in
# Settings -> Click Behavior, persisted by settings_manager.
START_DELAY_SECONDS = 5

# --- Human-like click behavior ------------------------------------------
# A plain pyautogui.click() is an instant, ~0ms down-then-up that's the
# same shape every single time. Instead, each click now does an explicit
# mouse-down, holds for a short random duration, then mouse-up - like an
# actual finger press. These bound that hold duration (seconds).
CLICK_HOLD_MIN = 0.05
CLICK_HOLD_MAX = 0.15

# --- Burst mode -----------------------------------------------------------
# When enabled, clicks are grouped into short "bursts" of BURST_CLICKS_MIN
# to BURST_CLICKS_MAX clicks spaced BURST_INTERVAL_MIN-MAX apart, followed
# by a longer BURST_REST_MIN-MAX pause before the next burst starts -
# clicking fast for a few reps, then easing off, rather than one constant
# even cadence. When disabled, clicking falls back to the plain
# CLICK_INTERVAL_MIN/MAX wait between every click.
BURST_MODE_ENABLED = False
BURST_CLICKS_MIN = 3
BURST_CLICKS_MAX = 7
BURST_INTERVAL_MIN = 0.05
BURST_INTERVAL_MAX = 0.15
BURST_REST_MIN = 1.0
BURST_REST_MAX = 2.5

# Whether the user has explicitly confirmed a scan region ON THIS MACHINE
# (via "Set Scan Region", or by saving from the calibrator/HSV tuner - both
# require a region to already be set). The SCAN_REGION default below was
# tuned on the dev's screen/resolution and is very unlikely to line up with
# anyone else's, so it doesn't count as "confirmed" on its own - this flag
# is what gates Start and drives the first-run hint in the GUI.
SCAN_REGION_CONFIRMED = False

# Crafting Settings
CRAFTING_MODE = 'AUTO' # 'AUTO' or 'MANUAL'
CLICK_INTERVAL_MIN = 0.45
CLICK_INTERVAL_MAX = 0.9

# Vision Detection Mode ('COLOR_BORDER' or 'TEMPLATE')
DETECTION_MODE = 'COLOR_BORDER'

# HSV Thresholds
LOWER_GOLD = (0, 120, 230)
UPPER_GOLD = (179, 255, 255)

# Boolean pixel mask (same size as SCAN_REGION), used only when
# DETECTION_MODE == 'COLOR_MASK'. Built by calibrator.py from wherever a
# lit-vs-unlit capture pair actually differed - could be a border, could be
# the middle of the item, whatever it turns out to be. None until a
# lit/unlit calibration has been run and saved.
DIFF_MASK = None

# Vision Settings
MIN_BORDER_MATCH_PERCENT = 1.0 
BORDER_THICKNESS = 12 
CONFIDENCE = 0.85 
SCAN_REGION = (264, 365, 99, 177)