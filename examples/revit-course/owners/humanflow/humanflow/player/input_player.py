"""
Precise playback with paste: exact xy + dt following, plus paste_next events.
Paste method: "type" = type text char-by-char (no keybind, nothing opens).
"shift_insert" / "ctrl_v" = clipboard + keybind (can open system panels on some setups).
"""
import json
import time
from pathlib import Path
from typing import Callable, Literal, Sequence

import pyperclip
from pynput.keyboard import Key, KeyCode

from humanflow.platform.dpi import ensure_dpi_aware
from humanflow.player.base import BasePlayer

PasteMethod = Literal["type", "shift_insert", "ctrl_v"]


class InputPlayer(BasePlayer):
    def __init__(
        self,
        recording_path: Path,
        lines_path: Path | None = None,
        lines: Sequence[str] | None = None,
        paste_delay_before: float = 0.35,
        paste_delay_after_copy: float = 0.08,
        paste_method: PasteMethod = "type",
        click_jitter_radius_px: float | None = None,
        value_resolver: Callable[[str], str] | None = None,
    ):
        super().__init__(click_jitter_radius_px=click_jitter_radius_px)
        self.recording_path = Path(recording_path)
        self.paste_delay_before = paste_delay_before
        self.paste_delay_after_copy = paste_delay_after_copy
        self.paste_method = paste_method
        # Optional live-variable hook: called at the paste point with each slot
        # value. A literal is returned unchanged; a "{{email_otp}}" template blocks
        # here until the code arrives. Default None keeps existing behaviour.
        self._value_resolver = value_resolver

        self.lines = []
        self.line_i = 0
        if lines is not None:
            self.lines = [str(ln) for ln in lines]
        elif lines_path:
            with open(lines_path, "r", encoding="utf-8") as f:
                self.lines = [ln.rstrip("\n") for ln in f]

    # ----------------
    # Lines + paste
    # ----------------
    def _next_line(self) -> str:
        if self.line_i >= len(self.lines):
            return ""
        s = self.lines[self.line_i]
        self.line_i += 1
        if self._value_resolver is not None:
            # Resolve at the paste point — this is where a {{email_otp}} template
            # blocks until the verification email arrives.
            s = self._value_resolver(s)
        return s

    def _paste_text(self, text: str) -> None:
        time.sleep(self.paste_delay_before)

        if self.paste_method == "type":
            if text and all(c.isascii() and c.isprintable() or c in "\n\t" for c in text):
                self._type_text(text)
            else:
                pyperclip.copy(text)
                time.sleep(self.paste_delay_after_copy)
                self.keyboard.press(Key.ctrl_l)
                time.sleep(0.02)
                self.keyboard.press(KeyCode.from_char("v"))
                self.keyboard.release(KeyCode.from_char("v"))
                self.keyboard.release(Key.ctrl_l)
            return

        pyperclip.copy(text)
        time.sleep(self.paste_delay_after_copy)
        if self.paste_method == "shift_insert":
            self.keyboard.press(Key.shift)
            time.sleep(0.02)
            self.keyboard.press(Key.insert)
            self.keyboard.release(Key.insert)
            self.keyboard.release(Key.shift)
        else:
            self.keyboard.press(Key.ctrl_l)
            time.sleep(0.02)
            self.keyboard.press(KeyCode.from_char("v"))
            self.keyboard.release(KeyCode.from_char("v"))
            self.keyboard.release(Key.ctrl_l)

    def _type_text(self, text: str, delay_per_char: float = 0.015) -> None:
        for c in text:
            try:
                if c == "\n":
                    self.keyboard.press(Key.enter)
                    self.keyboard.release(Key.enter)
                elif c == "\t":
                    self.keyboard.press(Key.tab)
                    self.keyboard.release(Key.tab)
                else:
                    key = KeyCode.from_char(c)
                    self.keyboard.press(key)
                    self.keyboard.release(key)
            except (ValueError, TypeError):
                pass
            time.sleep(delay_per_char)

    # ----------------
    # Load events
    # ----------------
    def _load_events(self):
        with open(self.recording_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # ----------------
    # Play
    # ----------------
    def play(self, start_delay_seconds: float = 3.0) -> None:
        ensure_dpi_aware()
        if start_delay_seconds > 0:
            print(f"Playback starting in {start_delay_seconds:.0f} seconds... (ESC to abort)")
            if self._interruptible_sleep(start_delay_seconds):
                print("Aborted during countdown.")
                return

        for event in self._load_events():
            if event.get("device") == "meta":
                continue

            dt = event.get("dt", 0.0)
            if self._interruptible_sleep(dt):
                print("Playback aborted.")
                return

            if event["device"] == "macro" and event["type"] == "paste_next":
                text = self._next_line()
                if not text.strip():
                    slots_used = self.line_i
                    print(f"Warning: paste slot {slots_used} has no content.")
                self._paste_text(text)
                continue

            if event["device"] == "mouse":
                self._handle_mouse(event)
            elif event["device"] == "keyboard":
                self._handle_keyboard(event)

        print("Playback finished.")
