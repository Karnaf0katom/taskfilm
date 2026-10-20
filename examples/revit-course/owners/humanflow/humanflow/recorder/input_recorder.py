import json
import time
from pathlib import Path
from pynput import mouse, keyboard
from pynput.keyboard import Key

from humanflow.player.key_resolver import KEY_MAP, resolve_paste_key


class InputRecorder:
    def __init__(self, output_path: Path, fresh: bool = True, paste_key: str | Key | None = "f8"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.fresh = fresh
        self.paste_key = paste_key
        self._paste_key_resolved = resolve_paste_key(paste_key)
        # Timestamps are set in start(), not here, so dt for the first event
        # doesn't include time spent waiting for the user to start recording.
        self._last_event_time: float = 0.0
        self._file = None

    def _write_event(self, event: dict) -> None:
        if self._file is not None:
            self._file.write(json.dumps(event) + "\n")
            self._file.flush()

    def _timestamp(self) -> float:
        now = time.time()
        dt = now - self._last_event_time
        self._last_event_time = now
        return round(dt, 6)

    # ----------------
    # Mouse Events
    # ----------------
    def on_click(self, x, y, button, pressed):
        event = {
            "device": "mouse",
            "type": "click",
            "x": x,
            "y": y,
            "button": str(button),
            "pressed": pressed,
            "dt": self._timestamp(),
            "ts": time.time()
        }
        self._write_event(event)

    def on_scroll(self, x, y, dx, dy):
        event = {
            "device": "mouse",
            "type": "scroll",
            "x": x,
            "y": y,
            "dx": float(dx),
            "dy": float(dy),
            "dt": self._timestamp(),
            "ts": time.time()
        }
        self._write_event(event)
        direction = "up" if dy < 0 else "down"
        print(f"scroll {direction} @ ({x}, {y})")

    # ----------------
    # Keyboard Events
    # ----------------
    def on_press(self, key):
        if key == self._paste_key_resolved:
            event = {
                "device": "macro",
                "type": "paste_next",
                "dt": self._timestamp()
            }
            self._write_event(event)
            return

        try:
            key_value = key.char
        except AttributeError:
            key_value = str(key)

        event = {
            "device": "keyboard",
            "type": "press",
            "key": key_value,
            "dt": self._timestamp(),
            "ts": time.time()
        }
        self._write_event(event)

    def on_release(self, key):
        if key == keyboard.Key.esc:
            return False
        if key == self._paste_key_resolved:
            return True

        try:
            key_value = key.char
        except AttributeError:
            key_value = str(key)

        event = {
            "device": "keyboard",
            "type": "release",
            "key": key_value,
            "dt": self._timestamp(),
            "ts": time.time()
        }
        self._write_event(event)

    # ----------------
    # Start Recording
    # ----------------
    def start(self):
        if self.fresh and self.output_path.exists():
            self.output_path.write_text("", encoding="utf-8")

        paste_name = getattr(self._paste_key_resolved, "name", "f8")
        print("Recording mouse + keyboard.")
        print(f"Paste slot: press {paste_name.upper()} where you want to paste later.")
        print(f"Output: {self.output_path.resolve()}")
        print("Press ESC to stop.\n")

        self.running = True

        # Reset timestamps here so the first dt is measured from when recording
        # actually begins, not from when the object was constructed.
        self._last_event_time = time.time()

        def stop_all():
            self.running = False
            if self._file is not None:
                self._file.flush()
            mouse_listener.stop()
            keyboard_listener.stop()

        def on_click_wrapper(x, y, button, pressed):
            if not self.running:
                return False
            self.on_click(x, y, button, pressed)

        def on_scroll_wrapper(x, y, dx, dy):
            if not self.running:
                return False
            self.on_scroll(x, y, dx, dy)

        def on_press_wrapper(key):
            if not self.running:
                return False
            self.on_press(key)

        def on_release_wrapper(key):
            if key == keyboard.Key.esc:
                print("\nESC pressed -> stopping recording")
                stop_all()
                return False
            self.on_release(key)

        # Keep file open for the whole session — one open/close, not per-event.
        with self.output_path.open("a", encoding="utf-8") as f:
            self._file = f

            mouse_listener = mouse.Listener(
                on_click=on_click_wrapper,
                on_scroll=on_scroll_wrapper,
            )
            keyboard_listener = keyboard.Listener(
                on_press=on_press_wrapper,
                on_release=on_release_wrapper
            )

            mouse_listener.start()
            keyboard_listener.start()

            mouse_listener.join()
            keyboard_listener.join()

        self._file = None
        print("Recording finished.")
