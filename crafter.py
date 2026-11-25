# crafter.py
import threading
import time
import random
import pyautogui
import keyboard
import config
from vision import is_item_lit

class AutoCrafter:
    def __init__(self, ui_callback):
        self.is_running = False
        self.thread = None
        self.ui_callback = ui_callback  # NOTE: must already be thread-safe (see gui.py)
        pyautogui.FAILSAFE = True

        # Craft counter: live numbers for the run in progress, plus a
        # "last run" snapshot that survives after stopping so the GUI has
        # something to show once is_running goes back to False. Read from
        # the GUI's polling loop (gui.py), not pushed - simple ints/floats,
        # no lock needed given the GIL and single-writer-thread pattern here.
        self.click_count = 0
        self.start_time = None
        self.last_run_clicks = 0
        self.last_run_seconds = 0.0

        # Burst-mode state: how many clicks are left in the burst currently
        # in progress. 0 means "no burst in progress, start a fresh one on
        # the next click". Reset at the start of every run so a previous
        # run's burst position never bleeds into the next one.
        self._burst_target = 0
        self._burst_count = 0

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.click_count = 0
            self.start_time = time.time()
            self._burst_target = 0
            self._burst_count = 0
            self.thread = threading.Thread(target=self._crafting_loop, daemon=True)
            self.thread.start()
            self.ui_callback("RUNNING", "#8FBF6B")

    def stop(self):
        if self.is_running:
            self.is_running = False
            self.ui_callback("STOPPED", "#C24C4C")

    def release_keys(self):
        try:
            pyautogui.keyUp('shift')
        except Exception:
            pass
        try:
            # Safety net: if we get interrupted mid-hold (stop/hotkey/error
            # while the button is physically down), make sure it doesn't
            # stay stuck down.
            pyautogui.mouseUp()
        except Exception:
            pass

    def _finalize_run_stats(self):
        """Snapshot click_count/elapsed into last_run_* exactly once per run,
        no matter which of the several ways the loop can end (hotkey, target
        found, failsafe, error). Called from the loop's `finally`, not from
        stop(), so it reflects when the thread actually exited rather than
        when a stop request was made."""
        if self.start_time is not None:
            self.last_run_clicks = self.click_count
            self.last_run_seconds = time.time() - self.start_time
            self.start_time = None

    def _interruptible_sleep(self, duration):
        """Sleep in small steps instead of one time.sleep(duration), so a
        stop/hotkey press during the wait takes effect immediately instead
        of only after the full duration has elapsed. Also flips
        is_running off itself on a hotkey hit, same as the main loop's
        check, since this gets called both between clicks and mid-click
        (during the mouse-down hold)."""
        slept = 0.0
        while slept < duration and self.is_running:
            if keyboard.is_pressed(config.TOGGLE_HOTKEY) or keyboard.is_pressed(config.EXIT_HOTKEY):
                self.is_running = False
                self.ui_callback("STOPPED", "#C24C4C")
                return
            step = min(0.01, duration - slept)
            time.sleep(step)
            slept += step

    def _perform_click(self):
        """Mouse down, hold for a short random duration, mouse up - instead
        of pyautogui.click(), which is an instant ~0ms down+up and looks
        identical on every single click."""
        pyautogui.mouseDown()
        hold = random.uniform(config.CLICK_HOLD_MIN, config.CLICK_HOLD_MAX)
        self._interruptible_sleep(hold)
        pyautogui.mouseUp()

    def _next_wait(self):
        """Seconds to wait after the click that was just made, before the
        next one. Plain mode: one random interval every time. Burst mode:
        a handful of clicks close together (BURST_INTERVAL apart), then a
        longer BURST_REST pause once that burst's target count is reached,
        then a new burst size is rolled and the pattern repeats."""
        if not config.BURST_MODE_ENABLED:
            return random.uniform(config.CLICK_INTERVAL_MIN, config.CLICK_INTERVAL_MAX)

        if self._burst_target <= 0:
            # Starting a new burst - decide how many clicks it'll run for.
            self._burst_target = random.randint(config.BURST_CLICKS_MIN, config.BURST_CLICKS_MAX)
            self._burst_count = 0

        self._burst_count += 1
        if self._burst_count >= self._burst_target:
            # That was the last click of this burst - reset so the next
            # call starts a fresh one, and rest before it begins.
            self._burst_target = 0
            return random.uniform(config.BURST_REST_MIN, config.BURST_REST_MAX)

        return random.uniform(config.BURST_INTERVAL_MIN, config.BURST_INTERVAL_MAX)

    def _crafting_loop(self):
        pyautogui.keyDown('shift')
        try:
            while self.is_running:
                # Hotkey check
                if keyboard.is_pressed(config.TOGGLE_HOTKEY) or keyboard.is_pressed(config.EXIT_HOTKEY):
                    self.is_running = False
                    self.ui_callback("STOPPED", "#C24C4C")
                    break

                # Vision check
                if is_item_lit():
                    self.is_running = False
                    self.ui_callback("TARGET FOUND - STOPPED", "#6EA8D6")
                    break

                # Logic split based on mode
                if config.CRAFTING_MODE == 'AUTO':
                    self._perform_click()
                    self.click_count += 1
                    if not self.is_running:
                        break
                    self._interruptible_sleep(self._next_wait())
                else:
                    # MANUAL MODE: Don't click. Sleep slightly to save CPU.
                    time.sleep(0.02)

        except pyautogui.FailSafeException:
            # Mouse hit a screen corner - pyautogui's built-in kill switch.
            self.ui_callback("FAILSAFE - MOUSE MOVED TO CORNER", "#C24C4C")
        except Exception as e:
            # Any other unexpected error (missing image, vision error, etc.)
            # used to kill the thread silently while the UI still said "RUNNING".
            self.ui_callback(f"ERROR: {e}", "#C24C4C")
        finally:
            self.is_running = False
            self._finalize_run_stats()
            self.release_keys()
