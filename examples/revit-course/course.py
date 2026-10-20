"""Windows course starter. Reuses hfrec/OBS, humanflow and edit-lane's voice seam.

This is recording/replay glue, not an autonomous Revit agent or a new editor.
The standalone handoff is assembled by jarvis/release/prepare_revit_course.py.
"""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def credentials(home: Path) -> dict:
    values = {}
    path = home / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in {"ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "OBS_WS_PASSWORD"}:
                    values[key.strip()] = value.strip()
    return values


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def foreground_is_revit() -> bool:
    """Check the executable, not a browser/document title containing 'Revit'."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return False
    try:
        size = wintypes.DWORD(32768)
        value = ctypes.create_unicode_buffer(size.value)
        return bool(kernel32.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size))) and Path(value.value).name.casefold() == "revit.exe"
    finally:
        kernel32.CloseHandle(handle)


def new_lesson(home: Path, title: str) -> Path:
    if not title.strip():
        raise ValueError("Give the lesson a title.")
    name = "".join(c if c.isalnum() else "-" for c in title.strip())[:60].strip("-") or "lesson"
    lesson = home / "lessons" / (name + "-" + uuid.uuid4().hex[:6])
    lesson.mkdir(parents=True)
    write_json(lesson / "lesson.json", {"title": title, "language": "he", "target_seconds": 60,
               "revit_version": "", "ui_language": "", "expected_result": "", "review": "not_reviewed"})
    (lesson / "narration.he.txt").write_text("", encoding="utf-8-sig")
    (lesson / "feedback.he.txt").write_text("מה לשנות בפעם הבאה?\n", encoding="utf-8-sig")
    shutil.copy2(home / "LESSON-TEMPLATE.he.txt", lesson / "teaching-notes.he.txt")
    return lesson


def validate_replay(session: dict, events: list, screen: tuple[int, int]) -> None:
    stream = session.get("streams", {}).get("input", {})
    if not stream.get("replayable") or stream.get("keys") != "raw":
        raise ValueError("This take was not recorded for replay. Use the teach/replay recording option.")
    expected = session.get("screen", {})
    if min(screen) <= 0 or (expected.get("width"), expected.get("height")) != screen:
        raise ValueError("Restore the monitor resolution and scaling used for the original take.")
    if not events or len(events) > 20000:
        raise ValueError("The replay must contain 1–20000 recorded events.")
    duration = 0.0
    for event in events:
        dt = event.get("dt", 0)
        if type(dt) not in (int, float) or not math.isfinite(dt) or not 0 <= dt <= 120:
            raise ValueError("Invalid replay timing.")
        duration += dt
        device, kind = event.get("device"), event.get("type")
        if device == "mouse" and kind in {"click", "scroll", "move"}:
            for field, maximum in (("x", screen[0]), ("y", screen[1])):
                value = event.get(field)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < maximum:
                    raise ValueError("Replay coordinates must be on the primary monitor.")
            if kind == "click" and (event.get("button") not in {"Button.left", "Button.right", "Button.middle"}
                                     or type(event.get("pressed")) is not bool):
                raise ValueError("Invalid recorded mouse button.")
            if kind == "scroll" and any(type(event.get(f)) not in (int, float)
                    or not math.isfinite(event[f]) or abs(event[f]) > 100 for f in ("dx", "dy")):
                raise ValueError("Invalid recorded scroll.")
        elif device == "keyboard" and kind in {"press", "release"}:
            key = event.get("key")
            if not isinstance(key, str) or not key or len(key) > 40 or "ctrl_alt" in key.lower():
                raise ValueError("Invalid recorded key.")
        else:
            raise ValueError("Only recorded mouse and keyboard actions can be replayed; paste slots are not supported.")
    if duration > 900:
        raise ValueError("Split the replay into lessons shorter than 15 minutes.")


class CourseKit:
    def __init__(self, home: Path):
        self.home = home.resolve()
        owners = self.home / "owners"
        self.hfrec = load("course_hfrec", owners / "capture-lane/hfrec.py")
        self.hfrec.HUMANFLOW_SRC = owners / "humanflow"
        sys.path.insert(0, str(self.hfrec.HUMANFLOW_SRC))
        self.delivery = load("course_delivery", owners / "edit-lane/course_delivery.py")

    def desktop(self):
        if sys.platform != "win32":
            raise ValueError("Recording and replay need the Windows PC running Revit.")
        from humanflow.platform.dpi import ensure_dpi_aware
        ensure_dpi_aware()

    def require_revit(self):
        if not foreground_is_revit():
            raise ValueError("Revit must stay in front. Playback has stopped; restore the starting view before retrying.")

    def countdown(self):
        print("עברו עכשיו לחלון Revit במסך הראשי. מתחילים בעוד 7 שניות. / Switch to Revit now.")
        time.sleep(7)
        self.require_revit()

    def check(self):
        checks = {name: bool(shutil.which(name)) for name in ("ffmpeg", "ffprobe")}
        checks["voice_key_present"] = bool(credentials(self.home).get("ELEVENLABS_API_KEY"))
        checks["windows"] = sys.platform == "win32"
        if checks["windows"]:
            self.desktop()
            self.hfrec.screen_size()
            obs = self.obs()
            checks["obs_connected"] = obs.client is not None
        print(json.dumps(checks, indent=2))
        return checks

    def obs(self):
        password = credentials(self.home).get("OBS_WS_PASSWORD") or os.environ.get("OBS_WS_PASSWORD", "")
        obs = self.hfrec.ObsSession(host="127.0.0.1", password=password)
        if obs.connect():
            raise ValueError("Open OBS, enable Tools > WebSocket Server Settings, and use menu 9 to enter its password.")
        if obs.client.get_record_status().output_active:
            raise ValueError("OBS is already recording. Stop that recording before starting a course take.")
        return obs

    def record(self, lesson: Path, *, replayable=False):
        self.desktop()
        obs = self.obs()
        previous = obs.client.get_current_program_scene().current_program_scene_name
        scene, source = "Taskfilm Course", "Taskfilm Primary Screen"
        scenes = {row["sceneName"] for row in obs.client.get_scene_list().scenes}
        if scene not in scenes:
            obs.client.create_scene(scene)
        inputs = {row["inputName"] for row in obs.client.get_input_list().inputs}
        if source not in inputs:
            obs.client.create_input(scene, source, "monitor_capture", {"monitor": 0, "capture_cursor": True}, True)
        elif source not in {row["sourceName"] for row in obs.client.get_scene_item_list(scene).scene_items}:
            raise ValueError("The Taskfilm OBS source was moved. Restore it to the Taskfilm Course scene first.")
        obs.client.set_current_program_scene(scene)
        before = set((lesson / "takes").glob("*/session.json"))
        try:
            if replayable:
                print("הקלטת לימוד שומרת גם את מה שמקלידים. עבדו רק בקובץ תרגול פתוח, בלי סיסמאות.")
            print("F9 = סיום הקלטה / Stop recording")
            self.countdown()
            password = credentials(self.home).get("OBS_WS_PASSWORD") or os.environ.get("OBS_WS_PASSWORD", "")
            self.hfrec.record(lesson.name, False, "", False, replayable, lesson / "takes", 4455, password)
        finally:
            obs.client.set_current_program_scene(previous)
        created = set((lesson / "takes").glob("*/session.json")) - before
        if len(created) != 1:
            raise ValueError("No unique new recording bundle was created.")
        manifest = created.pop()
        session = json.loads(manifest.read_text(encoding="utf-8"))
        raw = session["streams"]["screen"].get("path")
        if not raw or not Path(raw).is_file():
            raise ValueError("OBS did not return a recording. Check OBS output settings and record a short test.")
        self.delivery.probe(Path(raw))
        retained = manifest.parent / ("screen" + Path(raw).suffix)
        shutil.copy2(raw, retained)
        session["streams"]["screen"]["path"] = retained.name
        write_json(manifest, session)
        write_json(lesson / "current-take.json", {"session": str(manifest.relative_to(lesson))})
        print("ההקלטה נשמרה. צפו בה לפני הכנת הסרטון. / Recording saved.")

    def take(self, lesson: Path):
        pointer = json.loads((lesson / "current-take.json").read_text(encoding="utf-8"))
        manifest = (lesson / pointer["session"]).resolve()
        if not manifest.is_relative_to(lesson.resolve()):
            raise ValueError("Recording path must stay inside this lesson.")
        return manifest, json.loads(manifest.read_text(encoding="utf-8"))

    def replay(self, lesson: Path):
        self.desktop()
        manifest, session = self.take(lesson)
        events_path = manifest.parent / "input.jsonl"
        events = [json.loads(row) for row in events_path.read_text(encoding="utf-8").splitlines() if row.strip()]
        validate_replay(session, events, self.hfrec.screen_size())
        from humanflow.player.input_player import InputPlayer
        owner = self

        class RevitPlayer(InputPlayer):
            def _handle_mouse(self, event):
                owner.require_revit()
                return super()._handle_mouse(event)

            def _handle_keyboard(self, event):
                owner.require_revit()
                from humanflow.player.key_resolver import resolve_key
                key, _ = resolve_key(event.get("key", ""))
                result = super()._handle_keyboard(event)
                if key is not None:
                    if event["type"] == "press":
                        self.held_keys.add(key)
                    else:
                        self.held_keys.discard(key)
                return result

        player = RevitPlayer(events_path, click_jitter_radius_px=0)
        player.held_keys = set()
        print("פתחו עותק תרגול באותו מצב התחלתי. ESC עוצר את ההפעלה. / Restore the original starting state.")
        self.countdown()
        try:
            player.play(start_delay_seconds=0)
        finally:
            from pynput.keyboard import Key
            from pynput.mouse import Button
            # An interrupted macro must never leave a modifier or mouse button held.
            for key in player.held_keys:
                player.keyboard.release(key)
            for key in (Key.ctrl_l, Key.ctrl_r, Key.shift_l, Key.shift_r, Key.alt_l, Key.alt_r, Key.cmd):
                player.keyboard.release(key)
            for button in (Button.left, Button.right, Button.middle):
                player.mouse.release(button)
        print("בדקו את התוצאה ב-Revit. השחזור אינו אישור שהמודל נכון. / Check the Revit result.")

    def voice(self, lesson: Path):
        values = credentials(self.home)
        output = lesson / ("voice-" + uuid.uuid4().hex[:8] + ".mp3")
        text = (lesson / "narration.he.txt").read_text(encoding="utf-8-sig")
        self.delivery.narrate(text, output, key=values.get("ELEVENLABS_API_KEY", ""),
                              voice=values.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))
        write_json(lesson / "current-voice.json", {"file": output.name})
        os.startfile(output)

    def export(self, lesson: Path, *, narrated=False):
        manifest, session = self.take(lesson)
        source = (manifest.parent / session["streams"]["screen"]["path"]).resolve()
        if not source.is_relative_to(manifest.parent):
            raise ValueError("The recording must be inside its take folder.")
        voice = None
        if narrated:
            name = json.loads((lesson / "current-voice.json").read_text(encoding="utf-8"))["file"]
            voice = (lesson / name).resolve()
            if not voice.is_relative_to(lesson.resolve()):
                raise ValueError("The voice file must be inside this lesson.")
        output = lesson / ("lesson-" + uuid.uuid4().hex[:8] + ".mp4")
        self.delivery.deliver(source, output, voice=voice)
        print(str(output))
        os.startfile(output)


def menu(kit: CourseKit):
    current = None
    while True:
        print("\nרוויט תכל'ס — סרטוני הדגמה קצרים")
        print("שיעור: " + (current.name if current else "בחרו או צרו שיעור"))
        print("1 בדיקת התקנה | 2 שיעור חדש | 3 בחירת שיעור")
        print("4 הקלטה רגילה | 5 הקלטת לימוד לשחזור | 6 שחזור פעולות ב-Revit")
        print("7 קריינות עברית | 8 סרטון לכיתה | 10 סרטון עם קריינות")
        print("9 סיסמת OBS | 11 פתיחת תיקיית השיעור | 0 יציאה")
        choice = input("> ").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                kit.check()
            elif choice == "2":
                current = new_lesson(kit.home, input("שם השיעור: "))
                os.startfile(current)
            elif choice == "3":
                lessons = sorted((kit.home / "lessons").glob("*/lesson.json"))
                for i, path in enumerate(lessons, 1):
                    print(i, json.loads(path.read_text(encoding="utf-8"))["title"])
                index = int(input("מספר השיעור: "))
                if not 1 <= index <= len(lessons):
                    raise ValueError("Choose one of the listed lessons.")
                current = lessons[index - 1].parent
            elif choice == "9":
                password = getpass.getpass("OBS WebSocket password (hidden): ")
                if "\n" in password or "\r" in password:
                    raise ValueError("Password must be one line.")
                values = credentials(kit.home)
                values["OBS_WS_PASSWORD"] = password
                path = kit.home / ".env"
                path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
                path.chmod(0o600)
            elif current is None:
                print("צרו או בחרו קודם שיעור.")
            elif choice in {"4", "5"}:
                kit.record(current, replayable=choice == "5")
            elif choice == "6":
                kit.replay(current)
            elif choice == "7":
                kit.voice(current)
            elif choice in {"8", "10"}:
                kit.export(current, narrated=choice == "10")
            elif choice == "11":
                os.startfile(current)
        except (ValueError, OSError, KeyError, ImportError) as exc:
            print("לא הושלם / Could not complete: " + (str(exc) if isinstance(exc, ValueError)
                  else type(exc).__name__ + ". Check setup, the lesson files and OBS."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    kit = CourseKit(args.home)
    if args.check:
        kit.check()
    else:
        menu(kit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
