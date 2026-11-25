# vision.py
import cv2
import numpy as np
import pyautogui
import config

def compute_border_stats(img_bgr, lower, upper, thickness):
    """Core border-color-match math, shared by the live detector (check_border_color)
    and the HSV tuner (gui.py) so both are always looking at exactly the same
    calculation - tune against this and the live detector will behave the same way.

    img_bgr: BGR image (e.g. straight from a screenshot after RGB->BGR conversion)
    lower/upper: HSV bounds, each a 3-tuple/array
    thickness: border ring thickness in pixels

    Returns (match_percentage, color_mask, border_mask).
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    lower_bound = np.array(lower, dtype=np.uint8)
    upper_bound = np.array(upper, dtype=np.uint8)
    color_mask = cv2.inRange(hsv, lower_bound, upper_bound)

    h, w = color_mask.shape
    b_thick = max(1, min(thickness, h // 2, w // 2))

    border_mask = np.zeros((h, w), dtype=np.uint8)
    border_mask[0:b_thick, :] = 255
    border_mask[-b_thick:, :] = 255
    border_mask[:, 0:b_thick] = 255
    border_mask[:, -b_thick:] = 255

    border_gold_pixels = cv2.bitwise_and(color_mask, border_mask)
    total_border_pixels = np.count_nonzero(border_mask)
    matched_pixels = np.count_nonzero(border_gold_pixels)

    if total_border_pixels == 0:
        return 0.0, color_mask, border_mask

    match_percentage = (matched_pixels / total_border_pixels) * 100.0
    return match_percentage, color_mask, border_mask


def compute_mask_stats(img_bgr, lower, upper, region_mask):
    """Like compute_border_stats, but checks an arbitrary boolean pixel mask
    instead of assuming the interesting pixels are a border ring. Used by
    DETECTION_MODE == 'COLOR_MASK', where the mask was auto-derived by the
    calibrator from wherever a lit-vs-unlit capture actually differed
    (which may be a border, may be the item's center, may be an odd shape -
    it doesn't matter, we just monitor whatever changed).

    region_mask: bool array, same (h, w) as img_bgr, True = pixel to check.
    Returns (match_percentage, color_mask).
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_bound = np.array(lower, dtype=np.uint8)
    upper_bound = np.array(upper, dtype=np.uint8)
    color_mask = cv2.inRange(hsv, lower_bound, upper_bound)

    total_region_pixels = np.count_nonzero(region_mask)
    if total_region_pixels == 0:
        return 0.0, color_mask

    matched_pixels = np.count_nonzero((color_mask > 0) & region_mask)
    match_percentage = (matched_pixels / total_region_pixels) * 100.0
    return match_percentage, color_mask


def check_mask_color(region):
    try:
        screenshot = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        img_np = np.array(screenshot)
        bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        mask = config.DIFF_MASK
        if mask is None or mask.shape[:2] != bgr.shape[:2]:
            # No mask calibrated yet, or SCAN_REGION changed size since the
            # mask was built (e.g. region was re-picked after calibrating) -
            # fail safe instead of crashing or checking garbage-shaped data.
            print("[!] COLOR_MASK selected but no matching diff mask - recalibrate.")
            return False

        match_percentage, _ = compute_mask_stats(bgr, config.LOWER_GOLD, config.UPPER_GOLD, mask)
        return match_percentage >= config.MIN_BORDER_MATCH_PERCENT

    except Exception as e:
        print(f"[!] Vision Error: {e}")
        return False


def check_border_color(region):
    try:
        screenshot = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        img_np = np.array(screenshot)
        bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        match_percentage, _, _ = compute_border_stats(
            bgr, config.LOWER_GOLD, config.UPPER_GOLD, config.BORDER_THICKNESS
        )
        return match_percentage >= config.MIN_BORDER_MATCH_PERCENT

    except Exception as e:
        print(f"[!] Vision Error: {e}")
        return False

def is_item_lit():
    if config.DETECTION_MODE == 'COLOR_MASK':
        return check_mask_color(config.SCAN_REGION)
    elif config.DETECTION_MODE == 'COLOR_BORDER':
        return check_border_color(config.SCAN_REGION)
    else:
        try:
            return pyautogui.locateOnScreen(
                config.TARGET_IMAGE, 
                confidence=config.CONFIDENCE, 
                region=config.SCAN_REGION
            ) is not None
        except pyautogui.ImageNotFoundException:
            return False
        except Exception as e:
            # Covers a missing/corrupt TARGET_IMAGE file (OSError), bad region, etc.
            # Previously unhandled here -> would bubble up and kill the crafting thread.
            print(f"[!] Template match error: {e}")
            return False