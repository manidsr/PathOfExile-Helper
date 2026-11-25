# settings_manager.py
#
# Persists the things a user tunes at runtime (scan region, HSV thresholds,
# minimum border-match %) so they survive an app restart instead of resetting
# to the hardcoded defaults in config.py every time.
#
# This intentionally overwrites the module-level attributes on `config` in
# place, since crafter.py/vision.py/overlay.py all read those attributes live
# (e.g. `config.SCAN_REGION`) rather than taking a snapshot at import time.

import base64
import json
import os
import numpy as np
import config


def _encode_mask(mask):
    """Pack a bool (h, w) array down to 1 bit/pixel so it's cheap to keep in
    the settings JSON, and base64 it so json.dump can write it as a string."""
    packed = np.packbits(mask.astype(np.uint8))
    return {"shape": list(mask.shape), "data": base64.b64encode(packed.tobytes()).decode("ascii")}


def _decode_mask(obj):
    shape = tuple(obj["shape"])
    packed = np.frombuffer(base64.b64decode(obj["data"]), dtype=np.uint8)
    bits = np.unpackbits(packed)[: shape[0] * shape[1]]
    return bits.reshape(shape).astype(bool)


def load_settings():
    """Load saved settings (if any) and apply them onto the config module.
    Safe to call even if no settings file exists yet - config.py's defaults
    are left untouched in that case."""
    if not os.path.exists(config.SETTINGS_FILE):
        return

    try:
        with open(config.SETTINGS_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Error loading settings file: {e}")
        return

    region = data.get('scan_region')
    if region and len(region) == 4:
        config.SCAN_REGION = tuple(region)

    lower = data.get('lower_gold')
    if lower and len(lower) == 3:
        config.LOWER_GOLD = tuple(lower)

    upper = data.get('upper_gold')
    if upper and len(upper) == 3:
        config.UPPER_GOLD = tuple(upper)

    min_match = data.get('min_border_match_percent')
    if min_match is not None:
        config.MIN_BORDER_MATCH_PERCENT = float(min_match)

    mode = data.get('detection_mode')
    if mode:
        config.DETECTION_MODE = mode

    mask_obj = data.get('diff_mask')
    if mask_obj:
        try:
            config.DIFF_MASK = _decode_mask(mask_obj)
        except Exception as e:
            print(f"[!] Error decoding saved diff mask: {e}")
            config.DIFF_MASK = None

    # Whether the user has explicitly confirmed a scan region on THIS
    # machine. Older settings files predate this flag - if one already has
    # a saved scan_region at all, treat that as implicit confirmation so
    # existing users don't suddenly get told to redo something they already
    # did.
    confirmed = data.get('scan_region_confirmed')
    if confirmed is not None:
        config.SCAN_REGION_CONFIRMED = bool(confirmed)
    elif region:
        config.SCAN_REGION_CONFIRMED = True

    min_interval = data.get('click_interval_min')
    if min_interval is not None:
        config.CLICK_INTERVAL_MIN = float(min_interval)

    max_interval = data.get('click_interval_max')
    if max_interval is not None:
        config.CLICK_INTERVAL_MAX = float(max_interval)

    always_on_top = data.get('always_on_top')
    if always_on_top is not None:
        config.ALWAYS_ON_TOP = bool(always_on_top)

    toggle_hotkey = data.get('toggle_hotkey')
    if toggle_hotkey:
        config.TOGGLE_HOTKEY = toggle_hotkey

    overlay_hotkey = data.get('overlay_hotkey')
    if overlay_hotkey:
        config.OVERLAY_HOTKEY = overlay_hotkey

    exit_hotkey = data.get('exit_hotkey')
    if exit_hotkey:
        config.EXIT_HOTKEY = exit_hotkey

    start_delay = data.get('start_delay_seconds')
    if start_delay is not None:
        config.START_DELAY_SECONDS = float(start_delay)

    click_hold_min = data.get('click_hold_min')
    if click_hold_min is not None:
        config.CLICK_HOLD_MIN = float(click_hold_min)

    click_hold_max = data.get('click_hold_max')
    if click_hold_max is not None:
        config.CLICK_HOLD_MAX = float(click_hold_max)

    burst_mode_enabled = data.get('burst_mode_enabled')
    if burst_mode_enabled is not None:
        config.BURST_MODE_ENABLED = bool(burst_mode_enabled)

    burst_clicks_min = data.get('burst_clicks_min')
    if burst_clicks_min is not None:
        config.BURST_CLICKS_MIN = int(burst_clicks_min)

    burst_clicks_max = data.get('burst_clicks_max')
    if burst_clicks_max is not None:
        config.BURST_CLICKS_MAX = int(burst_clicks_max)

    burst_interval_min = data.get('burst_interval_min')
    if burst_interval_min is not None:
        config.BURST_INTERVAL_MIN = float(burst_interval_min)

    burst_interval_max = data.get('burst_interval_max')
    if burst_interval_max is not None:
        config.BURST_INTERVAL_MAX = float(burst_interval_max)

    burst_rest_min = data.get('burst_rest_min')
    if burst_rest_min is not None:
        config.BURST_REST_MIN = float(burst_rest_min)

    burst_rest_max = data.get('burst_rest_max')
    if burst_rest_max is not None:
        config.BURST_REST_MAX = float(burst_rest_max)


def save_settings():
    """Write the current tuning values from config back to disk. Everything
    the user can change at runtime lives in this one blob now (scan region,
    HSV/mask tuning, click intervals, hotkeys, always-on-top) so nothing
    needs its own separate save path or resets quietly on the next launch."""
    data = {
        'scan_region': list(config.SCAN_REGION) if config.SCAN_REGION else None,
        'scan_region_confirmed': config.SCAN_REGION_CONFIRMED,
        'lower_gold': list(config.LOWER_GOLD),
        'upper_gold': list(config.UPPER_GOLD),
        'min_border_match_percent': config.MIN_BORDER_MATCH_PERCENT,
        'detection_mode': config.DETECTION_MODE,
        'click_interval_min': config.CLICK_INTERVAL_MIN,
        'click_interval_max': config.CLICK_INTERVAL_MAX,
        'always_on_top': config.ALWAYS_ON_TOP,
        'toggle_hotkey': config.TOGGLE_HOTKEY,
        'overlay_hotkey': config.OVERLAY_HOTKEY,
        'exit_hotkey': config.EXIT_HOTKEY,
        'start_delay_seconds': config.START_DELAY_SECONDS,
        'click_hold_min': config.CLICK_HOLD_MIN,
        'click_hold_max': config.CLICK_HOLD_MAX,
        'burst_mode_enabled': config.BURST_MODE_ENABLED,
        'burst_clicks_min': config.BURST_CLICKS_MIN,
        'burst_clicks_max': config.BURST_CLICKS_MAX,
        'burst_interval_min': config.BURST_INTERVAL_MIN,
        'burst_interval_max': config.BURST_INTERVAL_MAX,
        'burst_rest_min': config.BURST_REST_MIN,
        'burst_rest_max': config.BURST_REST_MAX,
    }
    if config.DETECTION_MODE == 'COLOR_MASK' and config.DIFF_MASK is not None:
        data['diff_mask'] = _encode_mask(config.DIFF_MASK)
    try:
        with open(config.SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Error saving settings file: {e}")
