"""
Shared mouse/keyboard dispatch and sleep logic for all players.
"""
import time

try:
    import keyboard as _keyboard
except ModuleNotFoundError:
    _keyboard = None

from pynput.mouse import Controller as MouseController
from pynput.keyboard import Controller as KeyboardController

from humanflow.motion.jitter import adaptive_jitter
from humanflow.player.key_resolver import resolve_key, resolve_button, send_ctrl_alt_delete


class BasePlayer:
    def __init__(self, click_jitter_radius_px: float | None = None):
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.click_jitter_radius_px = click_jitter_radius_px

    def _esc_pressed(self) -> bool:
        return _keyboard is not None and _keyboard.is_pressed("esc")

    def _interruptible_sleep(self, dt: float) -> bool:
        """Sleep dt seconds in 50 ms slices. Returns True if ESC was pressed."""
        if dt <= 0:
            return False
        deadline = time.time() + dt
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))
            if self._esc_pressed():
                return True

    def _handle_mouse(self, event: dict) -> None:
        ev_type = event.get("type")

        if ev_type == "move":
            self.mouse.position = (event["x"], event["y"])

        elif ev_type == "scroll":
            self.mouse.scroll(event.get("dx", 0), event.get("dy", 0))

        elif ev_type == "click":
            button = resolve_button(event.get("button", ""))
            if button is None:
                return

            if event.get("pressed"):
                tx, ty = event["x"], event["y"]
                jittered = adaptive_jitter((tx, ty), self.mouse.position, self.click_jitter_radius_px)
                self.mouse.position = jittered
                time.sleep(0.01)
                self.mouse.press(button)
            else:
                self.mouse.release(button)

    def _handle_keyboard(self, event: dict) -> None:
        key = event.get("key", "")
        # Never replay ESC — it stops the recorder and would abort playback
        if key and (key == "Key.esc" or str(key).lower() in ("esc", "key.esc")):
            return

        resolved, is_ctrl_alt_delete = resolve_key(key)
        if is_ctrl_alt_delete:
            if event.get("type") == "press":
                if not send_ctrl_alt_delete():
                    print("Note: Ctrl+Alt+Delete not sent (may require admin).")
            return
        if resolved is None:
            return

        if event.get("type") == "press":
            self.keyboard.press(resolved)
        else:
            self.keyboard.release(resolved)
