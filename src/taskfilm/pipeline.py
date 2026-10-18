"""A bounded, resumable handoff over the existing capture/edit/render owners."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import signal
from string import Template
import subprocess
import sys
import time
from urllib.parse import quote
from uuid import uuid4

from . import __version__


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _hash(stream)


def _hash(stream) -> str:
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_take(take: Path, script: dict, script_sha256: str) -> list[Path]:
    """Bind every expected assertion to this script and retained screenshot bytes."""
    session = take / "session.json"
    manifest = json.loads(session.read_text(encoding="utf-8"))
    steps = manifest.get("steps", {})
    if (steps.get("ok") != len(script["steps"]) or steps.get("total") != len(script["steps"])
            or steps.get("failures") or steps.get("setup_problems")):
        raise ValueError("capture did not complete every step and setup action")
    if manifest.get("source", {}).get("script_sha256") != script_sha256:
        raise ValueError("capture belongs to different script bytes")
    if manifest.get("streams", {}).get("screen", {}).get("status") != "ok":
        raise ValueError("capture has no encoded screen stream")
    screen = take / "screen.mp4"
    if not screen.is_file() or screen.stat().st_size == 0:
        raise ValueError("capture screen recording is empty")
    expected = [step for step in script["steps"] if step.get("do") == "assert"]
    receipts = manifest.get("assertions", [])
    if not expected or len(receipts) != len(expected):
        raise ValueError("capture must retain every expected result assertion")
    files = [session, screen]
    for step, receipt in zip(expected, receipts):
        name = receipt.get("screenshot", "")
        if (receipt.get("status") != "passed" or receipt.get("selector") != step["selector"]
                or receipt.get("expected_text") != step["text"] or name != step["screenshot"]
                or Path(name).name != name or "\\" in name):
            raise ValueError("capture assertion does not match the expected task")
        shot = take / name
        if shot.is_symlink() or not shot.is_file() or digest(shot) != receipt.get("sha256"):
            raise ValueError("capture assertion screenshot is missing or changed")
        files.append(shot)
    files.extend(path for path in take.glob("*.jsonl") if path.is_file())
    return files


class Pipeline:
    def __init__(self, options):
        self.options = options
        self.root = options.out.resolve()
        self.record = self.root / "run.json"
        self.script_path = options.script.resolve()
        self.sources = sorted({path.resolve() for path in options.source})
        self.state: dict = {}
        self.reused: list[str] = []
        self.started = time.monotonic()
        self.phase = "prepare"

    def inputs(self) -> dict:
        return {"script": str(self.script_path), "script_sha256": digest(self.script_path),
                "revision": self.options.revision,
                "take": str(self.options.take.resolve()) if self.options.take else None,
                "sources": {str(path): digest(path) for path in self.sources}}

    def save(self):
        write_json(self.record, self.state)

    def checkpoint(self):
        if self.inputs() != self.state["inputs"]:
            self.state.update(status="stale", capture_verified=False, video_verified=False)
            raise ValueError("capture inputs or tracked source changed; check the new revision and use a new --out")

    def command(self, name: str, argv: list[str], cwd: Path | None = None) -> Path:
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        log = logs / f"{name}-{uuid4().hex[:8]}.log"
        self.state["log"] = str(log)
        self.save()
        env = os.environ.copy()
        env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
        with log.open("wb") as output:
            process = subprocess.Popen(argv, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=os.name != "nt")
            try:
                code = process.wait(timeout=self.options.timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                raise
        if code:
            raise ValueError(f"{name} exited {code}; inspect {log}")
        return log

    def owner(self, name: str, *argv) -> Path:
        return self.command(name, [sys.executable, "-m", "taskfilm", *map(str, argv)])

    def stage(self, name: str, key, action):
        self.phase = name
        self.checkpoint()
        receipt = self.state["stages"].get(name)
        key = fingerprint(key)
        if receipt and receipt["input"] == key:
            for filename, expected in receipt["outputs"].items():
                path = Path(filename)
                if not path.is_file() or digest(path) != expected:
                    self.state["video_verified"] = False
                    if name == "capture":
                        self.state["capture_verified"] = False
                    raise ValueError(f"retained {name} output changed: {path}; use a new --out")
            self.reused.append(name)
            return
        print(f"taskfilm: {name}", file=sys.stderr, flush=True)
        self.state.update(status="running", phase=name)
        if name in {"capture", "edit", "compose", "render", "verify"}:
            self.state["video_verified"] = False
            self.state["visual_review"] = "not_performed"
            for artifact in ("preview", "poster", "frames", "contact_sheet"):
                self.state["artifacts"].pop(artifact, None)
        if name in {"capture", "edit", "compose", "render"}:
            self.state["artifacts"].pop("movie", None)
        if name == "capture":
            self.state["capture_verified"] = False
        self.save()
        started = time.monotonic()
        files = action()
        self.checkpoint()
        self.state["stages"][name] = {"input": key,
            "outputs": {str(path): digest(path) for path in files},
            "seconds": round(time.monotonic() - started, 2)}
        self.save()

    def capture(self) -> list[Path]:
        if self.options.take:
            original = self.options.take.resolve()
            required = verify_take(original, self.script, self.state["inputs"]["script_sha256"])
            take = self.root / "takes" / f"import-{uuid4().hex[:8]}"
            take.mkdir(parents=True)
            # Copy only verified recording inputs. Preserve the complete original
            # bundle (including native exports) and never overwrite its edit plan.
            for path in required:
                shutil.copy2(path, take / path.name)
            self.state["artifacts"]["source_take"] = str(original)
        else:
            for tool in ("ffmpeg", "ffprobe"):
                if not shutil.which(tool):
                    raise ValueError(f"{tool} is required; run taskfilm doctor")
            self.owner("browser-check", "capture", "check")
            attempts = self.root / "takes" / uuid4().hex[:8]
            self.owner("capture", "capture", "rec", self.script_path, "--out-dir", attempts,
                       "--no-burn-captions", "--quiet")
            sessions = list(attempts.glob("*/session.json"))
            if len(sessions) != 1:
                raise ValueError("recorder did not produce exactly one take in its assigned directory")
            take = sessions[0].parent
        files = verify_take(take, self.script, self.state["inputs"]["script_sha256"])
        self.state["artifacts"]["take"] = str(take)
        self.state["artifacts"]["result_image"] = str(take / self.assertions[-1]["screenshot"])
        self.state["capture_verified"] = True
        return files

    def validate(self) -> list[Path]:
        self.owner("validate", "capture", "validate", self.script_path)
        return []

    def edit(self) -> list[Path]:
        take = Path(self.state["artifacts"]["take"])
        self.owner("edit", "edit", take, "--no-retime", "--no-aim")
        return [take / "plan.json"]

    def compose(self) -> list[Path]:
        project = self.root / "projects" / uuid4().hex[:8]
        viewport = self.script.get("viewport", {"width": 1920, "height": 1080})
        self.owner("compose", "compose", self.state["artifacts"]["take"], "--out", project,
                   "--no-title", "--max-scale", "1", "--keep-dead-air", "--note-top", "4",
                   "--width", viewport["width"], "--height", viewport["height"])
        self.state["artifacts"]["project"] = str(project)
        return sorted(path for path in project.rglob("*") if path.is_file())

    def render(self) -> list[Path]:
        label = "capture" if self.options.render_mode == "capture" else self.options.quality
        movie = self.root / "movies" / f"{label}-{uuid4().hex[:8]}.mp4"
        movie.parent.mkdir(exist_ok=True)
        captions = self.captions()
        if self.options.render_mode == "capture":
            # Keep the recorded pixels, cursor and click feedback. Explanations
            # are an editable subtitle track, without another browser/encode pass.
            self.command("prepare-movie", ["ffmpeg", "-v", "error", "-i",
                str(Path(self.state["artifacts"]["take"]) / "screen.mp4"),
                *(["-i", str(captions), "-map", "0:v:0", "-map", "0:a?", "-map", "1:s:0",
                   "-c", "copy", "-c:s", "mov_text"] if self.has_captions else
                  ["-map", "0:v:0", "-map", "0:a?", "-c", "copy"]),
                "-movflags", "+faststart", str(movie)])
        else:
            self.owner("render", "render", self.state["artifacts"]["project"], "--output", movie,
                       "--quality", self.options.quality)
        self.state["artifacts"]["movie"] = str(movie)
        return [movie, captions]

    def verify_video(self) -> list[Path]:
        movie = Path(self.state["artifacts"]["movie"])
        probe_log = self.command("probe", ["ffprobe", "-v", "error", "-show_format", "-show_streams",
                                             "-of", "json", str(movie)])
        probe = json.loads(probe_log.read_text(encoding="utf-8"))
        duration = float(probe["format"]["duration"])
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        plan = json.loads((Path(self.state["artifacts"]["take"]) / "plan.json").read_text(encoding="utf-8"))
        if (not math.isfinite(duration) or duration <= 0 or video["width"] <= 0 or video["height"] <= 0
                or abs(duration - float(plan["duration_s"])) > max(1, duration * .02)):
            raise ValueError("rendered movie has invalid dimensions or differs from the recorded duration")
        self.command("decode", ["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", str(movie),
                                "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"])
        review = self.root / "reviews" / uuid4().hex[:8]
        review.mkdir(parents=True)
        times = sorted({max(0, min(duration - .2, t)) for t in [min(.8, duration / 2), duration - .3]
                        + [float(beat["start"]) + .8 for beat in plan.get("beats", [])]
                        + [float(row["dt"]) for row in self.manifest["assertions"]]})
        if len(times) > 12:
            times = [times[round(i * (len(times) - 1) / 11)] for i in range(12)]
        frames = []
        for index, position in enumerate(times):
            frame = review / f"frame-{index:02d}.png"
            self.command(f"frame-{index:02d}", ["ffmpeg", "-v", "error", "-threads", "2", "-ss",
                str(round(position, 3)), "-i", str(movie), "-frames:v", "1", "-threads", "2", str(frame)])
            if not frame.is_file():
                raise ValueError("movie did not yield a review frame")
            frames.append(frame)
        from PIL import Image, ImageDraw
        tile_width, tile_height = 480, round(480 * video["height"] / video["width"])
        sheet = Image.new("RGB", (tile_width * 2, (tile_height + 28) * math.ceil(len(frames) / 2)), "#f3f2ed")
        draw = ImageDraw.Draw(sheet)
        for index, (frame, position) in enumerate(zip(frames, times)):
            x, y = (index % 2) * tile_width, (index // 2) * (tile_height + 28)
            with Image.open(frame) as original:
                sheet.paste(original.convert("RGB").resize((tile_width, tile_height)), (x, y))
            draw.text((x + 8, y + tile_height + 7), f"{position:.1f}s", fill="#17251f")
        contact = review / "contact.jpg"
        sheet.save(contact, quality=90)
        self.state["artifacts"].update(poster=str(frames[-1]), frames=[str(frame) for frame in frames],
                                       contact_sheet=str(contact), preview=str(self.root / "preview.html"))
        self.state.update(video_verified=True, duration_s=round(duration, 2),
            audio_review="not_performed" if any(row["codec_type"] == "audio" for row in probe["streams"])
                         else "not_applicable")
        return [*frames, contact, probe_log]

    def captions(self) -> Path:
        plan = json.loads((Path(self.state["artifacts"]["take"]) / "plan.json").read_text(encoding="utf-8"))
        captions = ["WEBVTT\n"]
        def stamp(seconds):
            milliseconds = round(max(0, seconds) * 1000)
            return f"{milliseconds // 3600000:02d}:{milliseconds // 60000 % 60:02d}:{milliseconds // 1000 % 60:02d}.{milliseconds % 1000:03d}"
        for beat in plan.get("beats", []):
            if beat.get("explain"):
                captions.append(f"{stamp(float(beat['start']))} --> {stamp(float(beat['end']))}\n"
                                f"{html.escape(beat['explain'])}\n")
        path = self.root / "captions.vtt"
        path.write_text("\n".join(captions), encoding="utf-8")
        self.has_captions = len(captions) > 1
        self.state["artifacts"]["captions"] = str(path)
        return path

    def preview(self):
        def url(name):
            return html.escape(quote(Path(self.state["artifacts"][name]).relative_to(self.root).as_posix()))
        plan = json.loads((Path(self.state["artifacts"]["take"]) / "plan.json").read_text(encoding="utf-8"))
        instructions = "".join(f"<li>{html.escape(beat['explain'])}</li>" for beat in plan.get("beats", [])
                               if beat.get("explain"))
        captions = self.captions()
        template = Path(__file__).parent / "templates/preview.html"
        page = Template(template.read_text(encoding="utf-8")).substitute(
            title=html.escape(self.script.get("name", "Feature walkthrough")), movie=url("movie"),
            language=html.escape(self.script.get("lang", "en")),
            captions_data=base64.b64encode(captions.read_bytes()).decode("ascii"),
            poster=url("poster"), result=url("result_image"), contact=url("contact_sheet"),
            revision=html.escape(self.options.revision), duration=self.state["duration_s"],
            instructions=instructions, assertions=len(self.assertions))
        (self.root / "preview.html").write_text(page, encoding="utf-8")

    def execute(self) -> int:
        if self.options.resume:
            self.state = json.loads(self.record.read_text(encoding="utf-8"))
            if self.state.get("schema") != "taskfilm-run/v1":
                raise ValueError("unsupported run record")
        else:
            self.state = {"schema": "taskfilm-run/v1", "inputs": self.inputs(), "stages": {},
                          "artifacts": {}, "capture_verified": False, "video_verified": False,
                          "visual_review": "not_performed", "audio_review": "not_performed"}
        self.state.pop("error", None)
        self.state.update(status="running", phase="prepare", quality=self.options.quality,
                          render_mode=self.options.render_mode)
        try:
            self.checkpoint()
            self.script = json.loads(self.script_path.read_text(encoding="utf-8"))
            self.assertions = [step for step in self.script.get("steps", []) if step.get("do") == "assert"]
            if not self.assertions:
                raise ValueError("run requires at least one assert step with a result screenshot")
            # A runtime change invalidates stage reuse without pretending to change the app revision.
            from .cli import VIDEO, OWNERS
            runtime = {name: digest(VIDEO / path) for name, path in OWNERS.items()
                       if name in {"capture", "edit", "compose"}}
            runtime.update(pipeline=digest(Path(__file__)), version=__version__)
            key = {"inputs": self.state["inputs"], "runtime": runtime}
            self.stage("validate", key, self.validate)
            self.stage("capture", key, self.capture)
            take = Path(self.state["artifacts"]["take"])
            verify_take(take, self.script, self.state["inputs"]["script_sha256"])
            self.state["capture_verified"] = True
            self.manifest = json.loads((take / "session.json").read_text(encoding="utf-8"))
            self.stage("edit", self.state["stages"]["capture"], self.edit)
            self.stage("compose", self.state["stages"]["edit"], self.compose)
            self.stage("render", [self.state["stages"]["compose"], self.options.quality,
                                  self.options.render_mode], self.render)
            self.stage("verify", self.state["stages"]["render"], self.verify_video)
            self.state["video_verified"] = True
            self.preview()
            self.checkpoint()
            self.state.update(status="rendered", phase="rendered")
        except KeyboardInterrupt:
            self.state.update(status="stopped", error="run interrupted; partial artifacts retained")
        except (ValueError, OSError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as exc:
            if self.state.get("status") != "stale":
                self.state["status"] = "blocked"
            self.state["error"] = str(exc)[:500]
        self.state.update(elapsed_s=round(time.monotonic() - self.started, 2), reused=self.reused)
        self.save()
        summary = {name: self.state.get(name) for name in ("status", "capture_verified", "video_verified",
                   "visual_review", "audio_review", "elapsed_s", "reused")}
        summary.update(revision=self.state["inputs"]["revision"], render_mode=self.options.render_mode, report=str(self.record),
                       artifacts=self.state["artifacts"])
        if "error" in self.state:
            summary.update(error=self.state["error"], phase=self.phase, log=self.state.get("log"))
        else:
            summary["next"] = "Inspect result_image and review frames; attach movie and preview in the feature handoff."
        if self.options.json:
            print(json.dumps(summary, separators=(",", ":")))
        else:
            print(json.dumps(summary, indent=2))
        return 0 if self.state["status"] == "rendered" else 130 if self.state["status"] == "stopped" else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="taskfilm run", description=__doc__)
    parser.add_argument("script", type=Path, help="capture JSON for the real, already checked app")
    parser.add_argument("--out", type=Path, required=True, help="owned local output directory")
    parser.add_argument("--resume", action="store_true", help="reuse unchanged completed stages from --out")
    parser.add_argument("--take", type=Path, help="import a verified take for these exact script bytes, without recapturing")
    parser.add_argument("--quality", choices=("draft", "looks", "delivery"), default="draft")
    parser.add_argument("--render-mode", choices=("capture", "hyperframes"),
                        help="capture keeps the recorded pixels (default); hyperframes renders editable motion")
    parser.add_argument("--revision", default="working", help="feature/build revision shown in the handoff")
    parser.add_argument("--source", type=Path, action="append", default=[], help="track a relevant source file; repeat as needed")
    parser.add_argument("--timeout", type=float, default=300, help="seconds allowed per external command")
    parser.add_argument("--json", action="store_true", help="one compact JSON result; progress goes to stderr")
    options = parser.parse_args(argv)
    options.render_mode = options.render_mode or ("hyperframes" if options.quality != "draft" else "capture")
    if options.render_mode == "capture" and options.quality != "draft":
        raise ValueError("--quality looks/delivery requires --render-mode hyperframes")
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    pipeline = Pipeline(options)
    # Validate inputs before creating a new output folder.
    pipeline.inputs()
    if not options.resume:
        pipeline.root.mkdir(parents=True, exist_ok=False)
    lock = pipeline.root / ".run.lock"
    previous_handler = signal.getsignal(signal.SIGTERM)
    def interrupted(*_):
        raise KeyboardInterrupt
    try:
        with lock.open("x"):
            try:
                signal.signal(signal.SIGTERM, interrupted)
                return pipeline.execute()
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
                lock.unlink(missing_ok=True)
    except FileExistsError:
        raise ValueError(f"a run owns {pipeline.root}; wait for it to exit before resuming") from None
