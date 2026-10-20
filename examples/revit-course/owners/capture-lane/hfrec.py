#!/usr/bin/env python3
"""hfrec — the capture front door for explainer videos.

One command records a *session bundle*: the screen (OBS), the face cam (ffmpeg, kept as its
own file so post can move it), and the input stream (humanflow's InputRecorder), all pinned to
one shared clock so a click at wall-clock T can be turned into a punch-in at video second X.

Why a bundle and not just an mp4: the pipeline downstream (course-watcher -> freecut ->
hyperframes) can already transcribe, segment and cut. What it cannot recover from a flat mp4 is
*where the operator clicked* and *which app was in front*. Those two streams are the whole
difference between a raw screen recording and an explainer that zooms and chapters itself.

Ownership: desktop input recording belongs to humanflow (capabilities.yaml:
"recording/vision/desktop=humanflow"). This module drives humanflow's InputRecorder and reuses its
event schema and writer; it does not reimplement one. Everything else here is session glue.

Usage:
    python hfrec.py devices                 # list webcam / audio devices ffmpeg can see
    python hfrec.py check                   # is OBS reachable, is ffmpeg present
    python hfrec.py rec "how freecut works" --webcam
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HUMANFLOW_SRC = REPO_ROOT / "apps/automation-platform/clicker-man/humanflow/src"

# Sampling the foreground window at 2 Hz is enough to catch an app switch but cheap enough that
# the shell-out on macOS never shows up in the recording.
WINDOW_SAMPLE_HZ = 2.0

# A click and the frame it belongs to must agree to well under one frame at 30 fps. Five paired
# reads of the OBS timecode, median-filtered, lands inside ~10 ms on a loaded machine.
OBS_CLOCK_SAMPLES = 5


# --------------------------------------------------------------------------------------
# shared clock
# --------------------------------------------------------------------------------------

def _timecode_seconds(timecode: str) -> float:
    """OBS reports 'HH:MM:SS.mmm' since the recording started."""
    hours, minutes, seconds = timecode.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# --------------------------------------------------------------------------------------
# OBS
# --------------------------------------------------------------------------------------

@dataclass
class ObsSession:
    """Screen capture. obs-websocket ships inside OBS 28+, so there is nothing to install."""

    host: str = "localhost"
    port: int = 4455
    password: str = ""
    client: object | None = None
    t0: float = 0.0
    sync: str = "unknown"
    output_path: str | None = None

    def connect(self) -> str:
        try:
            import obsws_python as obs
        except ImportError:
            return "obsws-python not installed (pip install obsws-python)"
        try:
            self.client = obs.ReqClient(
                host=self.host, port=self.port,
                password=self.password or os.environ.get("OBS_WS_PASSWORD", ""),
                timeout=5,
            )
        except Exception as exc:                       # noqa: BLE001 — any failure is "no OBS"
            self.client = None
            return f"{type(exc).__name__}: {exc}"
        return ""

    def start(self) -> None:
        """Start recording and pin the video's zero point to wall-clock time.

        Each sample brackets the request with a local read, so the timecode is attributed to the
        midpoint of the round trip rather than to whichever end happened to be measured.
        """
        if self.client is None:
            self.t0 = time.time()
            self.sync = "manual"
            return

        self.client.start_record()
        offsets: list[float] = []
        deadline = time.time() + 5.0
        while len(offsets) < OBS_CLOCK_SAMPLES and time.time() < deadline:
            before = time.time()
            status = self.client.get_record_status()
            after = time.time()
            if not getattr(status, "output_active", False):
                time.sleep(0.05)
                continue
            timecode = getattr(status, "output_timecode", None)
            if not timecode:
                time.sleep(0.05)
                continue
            offsets.append((before + after) / 2 - _timecode_seconds(timecode))
            time.sleep(0.05)

        if not offsets:
            # OBS answered but never went active — treat it as manual rather than silently
            # writing a t0 that is wrong by however long the start took.
            self.t0 = time.time()
            self.sync = "degraded"
            return

        offsets.sort()
        self.t0 = offsets[len(offsets) // 2]
        self.sync = "obs-websocket"

    def stop(self) -> None:
        if self.client is None:
            return
        try:
            response = self.client.stop_record()
            self.output_path = getattr(response, "output_path", None)
        except Exception as exc:                       # noqa: BLE001 — never lose the other streams
            print(f"  ! OBS stop failed ({exc}); stop the recording in OBS by hand.")


# --------------------------------------------------------------------------------------
# input stream (humanflow InputRecorder, driven directly)
# --------------------------------------------------------------------------------------

@dataclass
class InputTap:
    """Mouse + keyboard, written through humanflow's recorder.

    We drive the handlers instead of calling ``InputRecorder.start()`` because that method owns
    its own listeners and stops on ESC — and ESC is a key you press constantly while demoing
    (closing a modal, leaving a field). A session that dies at the first ESC is worse than none.

    Keystroke *content* is redacted by default. These recordings get posted; logging the actual
    characters would capture whatever is typed into a password field during a take.

    Two shapes of take, because they need opposite things:

    * **explainer** (default) — redacted keys, presses only. Enough for the planner to see *that*
      typing happened and hold the shot.
    * **replay** (``--replay``) — raw keys and key releases, so humanflow's ``InputPlayer`` can
      perform the take again on another machine. Releases are not optional there: the player
      presses on ``press`` and releases on anything else, so a press-only log leaves Ctrl and
      Shift stuck down for the rest of the run. Raw mode also restores InputRecorder's F8
      paste-slot, which is how you demo a login without recording the password.
    """

    out_path: Path
    t0: float
    redact_keys: bool = True
    record_releases: bool = False
    recorder: object | None = None
    _fh: object | None = None
    _mouse: object | None = None
    _keyboard: object | None = None
    on_stop_key: object | None = None
    counts: dict = field(default_factory=lambda: {"click": 0, "scroll": 0, "key": 0})

    def start(self) -> str:
        if str(HUMANFLOW_SRC) not in sys.path:
            sys.path.insert(0, str(HUMANFLOW_SRC))
        try:
            from humanflow.recorder.input_recorder import InputRecorder
            from pynput import keyboard, mouse
        except ImportError as exc:
            return f"{exc} (pip install pynput)"

        self.recorder = InputRecorder(self.out_path, fresh=True)
        self._fh = self.out_path.open("a", encoding="utf-8")
        self.recorder._file = self._fh                 # the writer InputRecorder.start() would set
        self.recorder._last_event_time = time.time()

        def on_click(x, y, button, pressed):
            if pressed:
                self.counts["click"] += 1
            self.recorder.on_click(x, y, button, pressed)

        def on_scroll(x, y, dx, dy):
            self.counts["scroll"] += 1
            self.recorder.on_scroll(x, y, dx, dy)

        def on_press(key):
            if self.on_stop_key is not None and self.on_stop_key(key):
                return False
            self.counts["key"] += 1
            if self.redact_keys:
                # Keep the beat, drop the content: post needs to know typing happened and when.
                name = getattr(key, "name", None)
                self.recorder._write_event({
                    "device": "keyboard", "type": "press",
                    "key": name if name else "char",
                    "dt": self.recorder._timestamp(), "ts": time.time(),
                })
            else:
                self.recorder.on_press(key)

        def on_release(key):
            # Only replay takes need releases; an explainer take would just double the file.
            if self.record_releases:
                self.recorder.on_release(key)

        self._mouse = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        self._keyboard = keyboard.Listener(on_press=on_press,
                                           on_release=on_release if self.record_releases else None)
        self._mouse.start()
        self._keyboard.start()
        return ""

    def stop(self) -> None:
        for listener in (self._mouse, self._keyboard):
            if listener is not None:
                listener.stop()
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()


# --------------------------------------------------------------------------------------
# foreground window stream
# --------------------------------------------------------------------------------------

def _active_window() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            user32 = ctypes.windll.user32
            handle = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(handle)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            return buffer.value
        if system == "Darwin":
            script = ('tell application "System Events" to get name of first '
                      'application process whose frontmost is true')
            return subprocess.run(["osascript", "-e", script], capture_output=True,
                                  text=True, timeout=2).stdout.strip()
        return subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                              capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:                                  # noqa: BLE001 — advisory stream only
        return ""


def screen_size() -> tuple[int, int]:
    """Desktop pixel size, so click coordinates can be normalised to 0..1.

    Normalising against the *desktop* rather than the video is what makes the plan survive OBS
    downscaling: a click at 0.42 of the way across the screen is 0.42 of the way across the frame
    whether OBS wrote 4K or 1080p.
    """
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)     # else Windows lies on scaled displays
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if system == "Darwin":
            script = 'tell application "Finder" to get bounds of window of desktop'
            out = subprocess.run(["osascript", "-e", script], capture_output=True,
                                 text=True, timeout=3).stdout
            parts = [int(p.strip()) for p in out.split(",")]
            return parts[2], parts[3]
        out = subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True,
                             text=True, timeout=3).stdout.split()
        return int(out[0]), int(out[1])
    except Exception:                                  # noqa: BLE001 — advisory; plan.py can override
        return 0, 0


class WindowSampler(threading.Thread):
    """Writes one line per *change* of foreground window — the chapter boundaries.

    Only transitions are recorded: a 20-minute take spent in one app should produce one line,
    not 2400 identical ones.
    """

    def __init__(self, out_path: Path, t0: float):
        super().__init__(daemon=True)
        self.out_path = out_path
        self.t0 = t0
        self.stopping = threading.Event()
        self.changes = 0

    def run(self) -> None:
        last = None
        with self.out_path.open("w", encoding="utf-8") as fh:
            while not self.stopping.is_set():
                title = _active_window()
                if title and title != last:
                    now = time.time()
                    fh.write(json.dumps({
                        "type": "window", "title": title,
                        "ts": now, "video_t": round(now - self.t0, 3),
                    }) + "\n")
                    fh.flush()
                    last = title
                    self.changes += 1
                self.stopping.wait(1.0 / WINDOW_SAMPLE_HZ)

    def stop(self) -> None:
        self.stopping.set()


# --------------------------------------------------------------------------------------
# webcam (separate file on purpose)
# --------------------------------------------------------------------------------------

def _webcam_command(device: str, out_path: Path) -> list[str]:
    """Video only — OBS already owns the microphone, and two processes on one mic is a fight."""
    system = platform.system()
    if system == "Windows":
        source = ["-f", "dshow", "-i", f"video={device}"]
    elif system == "Darwin":
        source = ["-f", "avfoundation", "-framerate", "30", "-i", f"{device}:none"]
    else:
        source = ["-f", "v4l2", "-i", device]
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *source,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out_path)]


def _default_webcam_device() -> str:
    system = platform.system()
    if system == "Darwin":
        return "0"
    if system == "Windows":
        return "Integrated Camera"
    return "/dev/video0"


def list_devices() -> None:
    system = platform.system()
    if system == "Windows":
        cmd = ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
    elif system == "Darwin":
        cmd = ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-f", "v4l2", "-list_formats", "all", "-i", "/dev/video0"]
    # ffmpeg exits non-zero after listing; the listing itself goes to stderr.
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stderr or result.stdout)


# --------------------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------------------

def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.strip()]
    return "".join(keep).strip("-").replace("--", "-")[:60] or "take"


def default_out_root() -> Path:
    override = os.environ.get("HFREC_OUT")
    if override:
        return Path(override).expanduser()
    return REPO_ROOT / "dropbox/recordings"


def check() -> int:
    print(f"platform    : {platform.system()} {platform.release()}")
    print(f"python      : {sys.version.split()[0]}")
    print(f"ffmpeg      : {shutil.which('ffmpeg') or 'MISSING — install ffmpeg'}")
    try:
        import pynput                                  # noqa: F401
        print("pynput      : ok")
    except ImportError:
        print("pynput      : MISSING — pip install pynput")
    print(f"humanflow   : {'ok' if (HUMANFLOW_SRC / 'humanflow').is_dir() else 'MISSING ' + str(HUMANFLOW_SRC)}")
    session = ObsSession()
    error = session.connect()
    print(f"obs-websocket: {'ok' if not error else error}")
    width, height = screen_size()
    print(f"screen      : {f'{width}x{height}' if width else 'UNKNOWN — pass --screen at plan time'}")
    print(f"out root    : {default_out_root()}")
    return 0


def selftest(seconds: int = 8) -> int:
    """Prove the input tap actually receives events before trusting a real take.

    macOS is the reason this exists: without Accessibility permission granted to the terminal,
    pynput starts cleanly, reports no error, and captures nothing. `check` cannot see that — only
    moving the mouse can. Better to find out in eight seconds than after a twenty-minute take.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tap = InputTap(Path(tmp) / "input.jsonl", time.time())
        error = tap.start()
        if error:
            print(f"input tap failed: {error}")
            return 1
        print(f"Move the mouse, click, and type for {seconds} seconds...")
        time.sleep(seconds)
        tap.stop()

    window = _active_window()
    print(f"  clicks captured : {tap.counts['click']}")
    print(f"  scrolls captured: {tap.counts['scroll']}")
    print(f"  keys captured   : {tap.counts['key']}")
    print(f"  active window   : {window or 'UNKNOWN — chapters will be empty'}")
    if not any(tap.counts.values()):
        print("\n  FAIL: nothing was captured.")
        if platform.system() == "Darwin":
            print("  macOS: System Settings > Privacy & Security > Accessibility,")
            print("  and add the terminal app you ran this from. Then restart the terminal.")
        return 1
    print("\n  OK — the input tap works.")
    return 0


def record(name: str, webcam: bool, webcam_device: str, raw_keys: bool, replay: bool,
           out_root: Path, obs_port: int, obs_password: str) -> int:
    # A replay take is useless without the keys it typed and the releases that end a modifier.
    raw_keys = raw_keys or replay
    stamp = time.strftime("%Y%m%d-%H%M%S")
    session_dir = out_root / f"{stamp}-{_slug(name)}"
    session_dir.mkdir(parents=True, exist_ok=True)

    obs = ObsSession(port=obs_port, password=obs_password)
    obs_error = obs.connect()
    if obs_error:
        print(f"  ! OBS not reachable: {obs_error}")
        print("    Start the recording in OBS yourself, then press Enter here.")
        print("    Sync will be approximate (about half a second) instead of exact.")
        input()
    obs.start()
    print(f"  screen  : OBS recording, clock={obs.sync}")

    stop_event = threading.Event()

    def is_stop_key(key) -> bool:
        if getattr(key, "name", None) == "f9":
            stop_event.set()
            return True
        return False

    tap = InputTap(session_dir / "input.jsonl", obs.t0, redact_keys=not raw_keys,
                   record_releases=replay, on_stop_key=is_stop_key)
    tap_error = tap.start()
    mode = "replayable, RAW KEYS" if replay else ("RAW KEYS" if raw_keys else "keys redacted")
    print(f"  input   : {f'ok ({mode})' if not tap_error else 'FAILED — ' + tap_error}")
    if raw_keys:
        print("            ! this take logs what you type — use F8 as a paste slot for secrets")

    sampler = WindowSampler(session_dir / "windows.jsonl", obs.t0)
    sampler.start()
    print("  windows : sampling foreground app")

    webcam_proc = None
    if webcam:
        device = webcam_device or _default_webcam_device()
        try:
            webcam_proc = subprocess.Popen(_webcam_command(device, session_dir / "webcam.mp4"),
                                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE)
            print(f"  webcam  : ffmpeg -> webcam.mp4 (device {device})")
        except FileNotFoundError:
            print("  webcam  : FAILED — ffmpeg not on PATH")

    print(f"\n  Recording. Press F9 (or Ctrl+C) to stop.\n  -> {session_dir}\n")
    try:
        while not stop_event.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()

    sampler.stop()
    tap.stop()
    if webcam_proc is not None:
        try:
            webcam_proc.communicate(input=b"q", timeout=10)     # let ffmpeg close the container
        except Exception:                              # noqa: BLE001
            webcam_proc.kill()
    obs.stop()

    duration = round(time.time() - obs.t0, 3)
    width, height = screen_size()
    manifest = {
        "name": name,
        "session_id": session_dir.name,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "t0_wallclock": obs.t0,
        "clock_source": obs.sync,
        "duration_s": duration,
        "host": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "screen": {"width": width, "height": height},
        "streams": {
            "screen": {"tool": "obs", "path": obs.output_path, "status": "ok" if not obs_error else "manual"},
            "input": {"tool": "humanflow.InputRecorder", "path": "input.jsonl",
                      "status": "ok" if not tap_error else "failed", "error": tap_error or None,
                      "keys": "raw" if raw_keys else "redacted", "counts": tap.counts,
                      # Whether humanflow's InputPlayer can perform this take again. Redacted keys
                      # cannot be typed, and without releases the player leaves modifiers held.
                      "replayable": bool(replay and not tap_error)},
            "windows": {"tool": "hfrec", "path": "windows.jsonl", "status": "ok",
                        "changes": sampler.changes},
            "webcam": {"tool": "ffmpeg", "path": "webcam.mp4" if webcam_proc else None,
                       "status": "ok" if webcam_proc else "off"},
        },
        # Every consumer downstream converts wall-clock to video time the same way. Writing the
        # rule into the manifest keeps that arithmetic out of four different readers.
        "video_time_rule": "video_t = event.ts - t0_wallclock",
    }
    (session_dir / "session.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"  done    : {duration:.1f}s · {tap.counts['click']} clicks · "
          f"{sampler.changes} app switches")
    print(f"  bundle  : {session_dir}")
    if obs.output_path:
        print(f"  screen  : {obs.output_path}  (move or point ingest at it)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an explainer session bundle.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify OBS, ffmpeg, pynput and humanflow are reachable")
    sub.add_parser("devices", help="list capture devices ffmpeg can see")
    st = sub.add_parser("selftest", help="prove the input tap really receives events (run this first on macOS)")
    st.add_argument("--seconds", type=int, default=8)

    rec = sub.add_parser("rec", help="record a session")
    rec.add_argument("name", help="what this take is about, e.g. \"how freecut works\"")
    rec.add_argument("--webcam", action="store_true", help="also record the face cam to its own file")
    rec.add_argument("--webcam-device", default="", help="override the ffmpeg capture device")
    rec.add_argument("--raw-keys", action="store_true",
                     help="log actual keystrokes (off by default: takes capture password fields)")
    rec.add_argument("--replay", action="store_true",
                     help="record a take humanflow's InputPlayer can perform again "
                          "(implies --raw-keys, adds key releases)")
    rec.add_argument("--out", default="", help="session root (default: repo dropbox/recordings)")
    rec.add_argument("--obs-port", type=int, default=4455)
    rec.add_argument("--obs-password", default="")

    args = parser.parse_args()
    if args.command == "check":
        return check()
    if args.command == "devices":
        list_devices()
        return 0
    if args.command == "selftest":
        return selftest(args.seconds)
    return record(args.name, args.webcam, args.webcam_device, args.raw_keys, args.replay,
                  Path(args.out).expanduser() if args.out else default_out_root(),
                  args.obs_port, args.obs_password)


if __name__ == "__main__":
    raise SystemExit(main())
