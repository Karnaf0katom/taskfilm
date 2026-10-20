"""Record an OpenGCUA Python workflow into the existing capture/edit contract.

The optional SDK owns its browser and reference validation. Taskfilm samples that
exact tab through its public Playwright bridge; it never replaces the SDK worker,
connects another window, or starts a model/provider. Programs are trusted local
Python, with the same host access as the caller.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
from importlib import metadata
import inspect
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

import webrec


SDK_VERSION = "0.1.2"
RPC_TIMEOUT_MS = 15000
STARTUP_TIMEOUT_MS = 60000
UPSTREAM_COMMIT = "b753f4c645b499e362d70303c23c26bd4ce24937"
UPSTREAM = "https://github.com/Tongyi-MAI/OpenGCUA"

# Observe actual DOM input, regardless of whether the program used AX, vision,
# or Playwright. Characters and field values never enter this queue. Navigation
# replaces the document, so the manifest explicitly reports that coverage gap.
INPUT_TAP_JS = r"""() => {
  if (!window.__taskfilmGCUA) {
    const tap = window.__taskfilmGCUA = {events: [], dropped: 0};
    const push = event => {
      if (tap.events.length >= 5000) { tap.dropped++; return; }
      tap.events.push({...event, ts: Date.now() / 1000});
    };
    for (const kind of ['pointermove', 'pointerdown', 'pointerup']) {
      addEventListener(kind, e => {
        if (!e.isTrusted) return;
        const x = e.clientX, y = e.clientY;
        window.__hfcursor?.at(x, y);
        if (kind === 'pointerdown') window.__hfcursor?.press();
        if (kind === 'pointerup') window.__hfcursor?.release();
        push({device: 'mouse', type: kind === 'pointermove' ? 'move' : 'click',
              x, y, ...(kind === 'pointermove' ? {} : {
                button: ['left', 'middle', 'right'][e.button] || 'other',
                pressed: kind === 'pointerdown'})});
      }, true);
    }
    addEventListener('wheel', e => {
      if (e.isTrusted) push({device: 'mouse', type: 'scroll',
        x: e.clientX, y: e.clientY, dx: e.deltaX, dy: e.deltaY});
    }, {capture: true, passive: true});
    for (const kind of ['keydown', 'keyup']) {
      addEventListener(kind, e => {
        if (e.isTrusted) push({device: 'keyboard',
          type: kind === 'keydown' ? 'press' : 'release',
          key: e.key.length === 1 ? 'char' : e.key});
      }, true);
    }
  }
  const tap = window.__taskfilmGCUA;
  return {document: performance.timeOrigin, title: document.title,
          events: tap.events.splice(0), dropped: tap.dropped,
          width: innerWidth, height: innerHeight};
}"""


def runtime_class():
    """Load the preview only when requested; ordinary Taskfilm stays Python 3.10+."""
    if sys.version_info < (3, 11):
        raise ValueError("OpenGCUA capture requires Python 3.11+; ordinary capture supports 3.10+")
    try:
        version = metadata.version("qwen-intelligence-sdk")
    except metadata.PackageNotFoundError:
        raise ValueError("optional OpenGCUA SDK is missing; install the matching qwen-intelligence-sdk "
                         f"{SDK_VERSION} wheel from {UPSTREAM}/releases/tag/v{SDK_VERSION}, then run "
                         "mu setup browser --engine chromium") from None
    if version != SDK_VERSION:
        raise ValueError(f"OpenGCUA capture supports qwen-intelligence-sdk {SDK_VERSION}; found {version}")
    from qwen_intelligence import Runtime
    return Runtime


def validate_options(program: Path, url: str, out: Path, width: int, height: int,
                     fps: float, timeout: float) -> bytes:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("--url must be an http(s) page without embedded credentials")
    if out.exists() or out.is_symlink():
        raise ValueError("capture output must be a new directory")
    if any(type(n) is not int or not 320 <= n <= 3840 or n % 2 for n in (width, height)):
        raise ValueError("viewport dimensions must be even integers between 320 and 3840")
    for name, value, lower, upper in (("fps", fps, 1, 15), ("timeout", timeout, 1, 600)):
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    if not program.is_file() or program.suffix != ".py" or program.stat().st_size > 256 * 1024:
        raise ValueError("program must be an existing .py file of at most 256 KiB")
    data = program.read_bytes()
    # Check syntax before allocating the take or starting a browser. Execute
    # these same bytes later, so the manifest binds the actual program.
    compile(data, str(program), "exec")
    return data


def load_program(data: bytes, source: Path):
    namespace = {"__name__": "taskfilm_capture_program", "__file__": str(source.resolve())}
    exec(compile(data, str(source), "exec"), namespace)
    run = namespace.get("run")
    if not inspect.iscoroutinefunction(run):
        raise ValueError("program must define async def run(tab, film)")
    inspect.signature(run).bind(None, None)
    return run


def screenshot_bytes(data: Any, width: int, height: int) -> bytes:
    if not isinstance(data, bytes) or not data:
        raise ValueError("SDK screenshot did not return image bytes")
    with Image.open(io.BytesIO(data)) as image:
        if image.size != (width, height):
            raise ValueError("recorded tab viewport changed")
        image.verify()
    return data


@dataclass
class TabRecorder:
    tab: Any
    bundle: webrec.Bundle
    width: int
    height: int
    fps: float
    stream: webrec.Screencast = field(init=False)
    documents: int = 0
    dropped_inputs: int = 0
    inputs_collected: bool = False
    _document: float | None = None
    _last_ts: float = 0

    def __post_init__(self):
        self.stream = webrec.Screencast(self.bundle.dir / "_frames")
        self.stream.frames_dir.mkdir()

    async def prepare(self):
        # evaluate is a WRITE in the SDK contract. Install the event tap before
        # the program observes anything, then leave its live references alone.
        # Tab.evaluate requires a JSON result. The existing overlay's IIFE
        # returns undefined, which the SDK reports as ACTION_OUTCOME_UNKNOWN.
        await self.tab.evaluate("() => {\n" + webrec.OVERLAY_JS + "\nreturn true;\n}",
                                timeout_ms=RPC_TIMEOUT_MS)
        sample = await self.tab.evaluate(INPUT_TAP_JS, timeout_ms=RPC_TIMEOUT_MS)
        if (sample["width"], sample["height"]) != (self.width, self.height):
            raise ValueError("recorded tab viewport changed")
        self._document = sample["document"]
        self.documents = 1
        self.bundle.chapter(sample["title"] or "Browser workflow")

    async def collect_inputs(self):
        # Read/drain only after the program has stopped using observed targets.
        # The bounded queue lives in the page for the duration of the program.
        sample = await self.tab.evaluate(INPUT_TAP_JS, timeout_ms=RPC_TIMEOUT_MS)
        if sample["document"] != self._document:
            self.documents += 1
            self.bundle.chapter(sample["title"] or "Browser workflow")
        self.dropped_inputs = max(self.dropped_inputs, sample["dropped"])
        for event in sample["events"]:
            event["dt"] = round(max(0, event["ts"] - self._last_ts), 6) if self._last_ts else 0
            self._last_ts = event["ts"]
            if event["type"] in {"move", "scroll"}:
                self.bundle.counts[event["type"]] += 1
            elif event["type"] == "click" and event["pressed"]:
                self.bundle.counts["click"] += 1
            elif event["device"] == "keyboard" and event["type"] == "press":
                self.bundle.counts["key"] += 1
            self.bundle._write(event)
        self.inputs_collected = True

    async def capture(self):
        # screenshot is a READ in the SDK contract. In particular, do not use
        # ui.vision.observe, which would replace the program's coordinate history.
        before = time.time()
        data = await self.tab.playwright.screenshot(type="jpeg", quality=webrec.SCREENCAST_QUALITY,
                                                    full_page=False, timeout_ms=RPC_TIMEOUT_MS)
        stamp = (before + time.time()) / 2
        data = screenshot_bytes(data, self.width, self.height)
        path = self.stream.frames_dir / f"f{len(self.stream.frames):06d}.jpg"
        path.write_bytes(data)
        self.stream.frames.append((stamp, path))
        if self.bundle.t0 is None:
            self.bundle.t0 = stamp

    async def loop(self):
        while True:
            started = time.monotonic()
            await self.capture()
            await asyncio.sleep(max(0, 1 / self.fps - (time.monotonic() - started)))


class Film:
    """Story marks and native result evidence alongside unmodified SDK handles."""

    def __init__(self, mu, tab, bundle, width, height):
        self.mu, self.tab, self.bundle = mu, tab, bundle
        self.width, self.height = width, height
        self.observations = 0

    def beat(self, id: str, *, vo: str = "", explain: str = "", show: str = "", lang: str = "en"):
        if not isinstance(id, str) or not id or not (vo or explain):
            raise ValueError("a beat needs an id and narration or explanation")
        self.bundle.beat(id, vo=vo, explain=explain, show=show, lang=lang)

    async def observe(self, *, timeout_ms: int = RPC_TIMEOUT_MS):
        # The SDK's browser default is 1.5 s. Real AX capture on a contended,
        # CPU-only host takes several seconds even without recording.
        observation = await self.tab.ui.ax.observe(timeout_ms=timeout_ms)
        await self.mu.emit(observation)
        return observation

    async def deliver(self, output):
        """Retain explicitly emitted observations without storing model transcripts."""
        self.observations += 1
        kind = output.get("type")
        image = output.get("data") if kind == "image" else None
        suffix = ".png" if output.get("mime_type") == "image/png" else ".jpg" if image else ".txt"
        name = f"observation-{self.observations:04d}{suffix}"
        data = image if image is not None else str(output.get("text", "")).encode("utf-8")
        with (self.bundle.dir / name).open("xb") as handle:
            handle.write(data)
        with (self.bundle.dir / "observations.jsonl").open("a", encoding="utf-8") as journal:
            journal.write(json.dumps({"type": kind, "path": name, "ts": time.time(),
                                      "sha256": hashlib.sha256(data).hexdigest()}) + "\n")

    async def assert_text(self, selector: str, text: str, *, screenshot: str, timeout: float = 15):
        if (not isinstance(selector, str) or not selector.strip() or not isinstance(text, str)
                or not 0 < len(text) <= 2000 or not isinstance(screenshot, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.png", screenshot)
                or ".." in screenshot or screenshot.startswith("observation-")):
            raise ValueError("assert_text needs a selector, expected text and a safe .png basename")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("assertion timeout must be finite, 0 < timeout <= 60")
        receipt = {"selector": selector, "expected_text": text, "status": "failed",
                   "visual_verification": "not_performed"}
        self.bundle.assertions.append(receipt)
        locator = self.tab.playwright.locator(selector)
        deadline = time.monotonic() + timeout
        def remaining_ms():
            return max(1, min(RPC_TIMEOUT_MS, int((deadline - time.monotonic()) * 1000)))
        while time.monotonic() < deadline:
            if (await locator.count(timeout_ms=remaining_ms()) == 1
                    and await locator.is_visible(timeout_ms=remaining_ms())
                    and await locator.inner_text(timeout_ms=remaining_ms()) == text):
                data = await self.tab.playwright.screenshot(type="png", full_page=False,
                                                            timeout_ms=remaining_ms())
                data = screenshot_bytes(data, self.width, self.height)
                with (self.bundle.dir / screenshot).open("xb") as handle:
                    handle.write(data)
                receipt.update(status="passed", screenshot=screenshot, bytes=len(data),
                               sha256=hashlib.sha256(data).hexdigest(),
                               dt=round(time.time() - self.bundle.t0, 3))
                return receipt
            await asyncio.sleep(.1)
        raise AssertionError("expected visible text was not observed")


async def run_recorded_program(run, tab, film, recorder, timeout):
    """Recorder failure and deadline both stop the program; always join both tasks."""
    capture = asyncio.create_task(recorder.loop())
    program = asyncio.create_task(run(tab, film))
    try:
        done, _ = await asyncio.wait({capture, program}, timeout=timeout,
                                     return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise TimeoutError("OpenGCUA program timed out")
        if capture in done:
            await capture
            raise ValueError("recorder stopped before the program")
        await program
    finally:
        for task in (capture, program):
            task.cancel()
        await asyncio.gather(capture, program, return_exceptions=True)


async def record_program(args) -> int:
    program, out = Path(args.program), Path(args.out).absolute()
    source = validate_options(program, args.url, out, args.width, args.height, args.fps, args.timeout)
    Runtime = runtime_class()
    if not shutil.which("ffmpeg"):
        raise ValueError("OpenGCUA capture requires FFmpeg")
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    bundle = webrec.Bundle(out)
    recorder = film = None
    errors = []
    completed = False
    encoded, detail = False, "recording did not start"
    phase = "sdk_start"
    ended = None
    try:
        async with Runtime() as runtime:
            await runtime.add_browser_factory("taskfilm", engine="chromium", headless=not args.headed,
                viewport={"width": args.width, "height": args.height})
            async with runtime.session(output=lambda output: film.deliver(output)) as mu:
                phase = "browser_start"
                browser = await mu.browsers.create(name="taskfilm-capture", provider="taskfilm",
                                                   timeout_ms=STARTUP_TIMEOUT_MS)
                phase = "tab_start"
                tab = await browser.browser.new_tab(timeout_ms=STARTUP_TIMEOUT_MS)
                phase = "navigation"
                await tab.goto(args.url, timeout_ms=STARTUP_TIMEOUT_MS)
                film = Film(mu, tab, bundle, args.width, args.height)
                recorder = TabRecorder(tab, bundle, args.width, args.height, args.fps)
                phase = "first_frame"
                await recorder.prepare()
                await recorder.capture()
                phase = "program"
                run = load_program(source, program)
                try:
                    await run_recorded_program(run, tab, film, recorder, args.timeout)
                finally:
                    try:
                        await recorder.collect_inputs()
                    except Exception as exc:
                        errors.append({"stage": "input_collection", "type": type(exc).__name__})
                phase = "final_frame"
                await recorder.capture()
                ended = time.time()
                completed = True
                phase = "sdk_close"
    except (Exception, asyncio.CancelledError) as exc:
        # Browser/provider errors may carry signed URLs or page content. Retain
        # the class, never the raw exception or arbitrary program output.
        error = {"stage": phase, "type": type(exc).__name__}
        code = getattr(exc, "code", None)
        if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,80}", code):
            error["code"] = code
        errors.append(error)
    finally:
        ended = ended or time.time()
        bundle.close()
        if recorder is not None:
            try:
                encoded, detail = recorder.stream.encode(out / "screen.mp4", ended)
            except Exception as exc:
                detail = "encoding failed"
                errors.append({"stage": "encode", "type": type(exc).__name__})
        assertions_ok = bool(bundle.assertions) and all(r["status"] == "passed" for r in bundle.assertions)
        ok = encoded and completed and not errors and all(r["status"] == "passed" for r in bundle.assertions)
        parsed = urlsplit(args.url)
        manifest = {
            "name": program.stem, "session_id": out.name,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "clock_source": "SDK screenshot RPC midpoint; DOM input wall clock (sampled)", "lang": "en",
            "t0_wallclock": bundle.t0, "duration_s": round(max(0, ended - (bundle.t0 or ended)), 3),
            "source": {"kind": "web", "url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")),
                       "script": program.name, "script_sha256": hashlib.sha256(source).hexdigest()},
            "screen": {"width": args.width, "height": args.height},
            "streams": {
                "screen": {"tool": "OpenGCUA Playwright screenshots + webrec FFmpeg encoder",
                           "path": "screen.mp4" if encoded else None, "status": "ok" if encoded else "failed",
                           "error": None if encoded else detail,
                           "frames": len(recorder.stream.frames) if recorder else 0, "dropped": 0,
                           "requested_fps": args.fps, "capture_mode": "sampled",
                           "timestamp_source": "host RPC midpoint"},
                "input": {"tool": "recorded tab DOM events (humanflow schema)", "path": "input.jsonl",
                          "status": "failed" if recorder is None or not recorder.inputs_collected else "partial" if (
                              recorder.documents > 1 or recorder.dropped_inputs) else "ok",
                          "documents": recorder.documents if recorder else 0,
                          "dropped_events": recorder.dropped_inputs if recorder else 0,
                          "scope": "main frame; navigation may lose pending events; programmatic edits are not keystrokes",
                          "keys": "redacted", "counts": bundle.counts, "replayable": False},
                "windows": {"path": "windows.jsonl", "status": "ok", "changes": bundle.chapters},
                "beats": {"path": "beats.jsonl", "status": "ok" if bundle.beats else "none",
                          "count": bundle.beats, "burned": False},
                "webcam": {"path": None, "status": "off"}},
            "steps": {"total": 1, "ok": int(completed), "failures": errors, "setup_problems": []},
            "assertions": bundle.assertions,
            "result_verification": "dom_assertions_passed" if assertions_ok else "not_verified",
            "visual_verification": "not_performed",
            "driver": {"name": "OpenGCUA", "sdk_version": SDK_VERSION, "upstream": UPSTREAM,
                       "commit": UPSTREAM_COMMIT, "browser_scope": "one fresh SDK-owned tab",
                       "program_sha256": hashlib.sha256(source).hexdigest(),
                       "program": program.name, "completed": completed, "status": "ok" if ok else "failed"},
            "video_time_rule": "video_t = event.ts - t0_wallclock",
        }
        (out / "session.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if encoded and not args.keep_frames and recorder:
            shutil.rmtree(recorder.stream.frames_dir)
    print(json.dumps({"take": str(out), "status": "ok" if ok else "failed", "errors": errors,
                      "result_verification": manifest["result_verification"],
                      "next": f"taskfilm edit {out} --no-retime"}, indent=2))
    return 0 if ok else 1


def add_parser(subparsers):
    parser = subparsers.add_parser("gcua", help="record a trusted Python workflow through the optional OpenGCUA SDK")
    parser.add_argument("program", help="trusted Python file defining async def run(tab, film)")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, help="new take directory")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=8, help="requested screenshot sampling rate (1–15); output is encoded at 30 fps")
    parser.add_argument("--timeout", type=float, default=120, help="program deadline in seconds (1–600)")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--keep-frames", action="store_true")
    return parser
