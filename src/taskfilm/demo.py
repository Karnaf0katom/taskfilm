"""A first-run recipe over the existing owners, with a temporary local sample server."""
from __future__ import annotations

from contextlib import redirect_stdout
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread


def demonstrate(destination: Path, *, render: bool = False, quality: str = "looks",
                mode: str = "lesson", format: str = "landscape") -> dict:
    from . import cli
    from .cli import initialize, node_version, render_project, run_owner

    if mode not in {"lesson", "promo"}:
        raise ValueError("demo mode must be lesson or promo")
    if format not in {"landscape", "portrait", "both"}:
        raise ValueError("demo format must be landscape, portrait or both")
    if mode == "lesson" and format != "landscape":
        raise ValueError("lesson demo supports only landscape format")

    # Check before resolving: a dangling destination symlink must never be used.
    if destination.exists() or destination.is_symlink():
        raise ValueError("demo destination must be a new directory; existing files are never overwritten")
    destination = destination.resolve()
    if mode == "promo":
        missing_dependencies = [name for name in ("numpy", "scipy")
                                if importlib.util.find_spec(name) is None]
        missing_owners = [name for name, path in cli.OWNERS.items()
                          if not (cli.VIDEO / path).is_file()]
        missing_tools = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
        if render:
            version = node_version()
            if not shutil.which("npm"):
                missing_tools.append("npm")
            if not version or int(version.split(".")[0][1:]) < 22:
                missing_tools.append("Node.js 22+")
        if missing_dependencies or missing_owners or missing_tools:
            details = ", ".join(missing_dependencies + missing_owners + missing_tools)
            raise ValueError(f"promo demo prerequisites are missing: {details}")
    elif render:
        version = node_version()
        if not version or int(version.split(".")[0][1:]) < 22 or not shutil.which("npm"):
            raise ValueError("demo --render requires Node.js 22+ and npm; omit --render to prepare the lesson")
    destination.mkdir(parents=True)
    logs = destination / "logs"
    logs.mkdir()

    def execute(stage: str, command: str, arguments: list) -> None:
        print(f"taskfilm demo: {stage}", file=sys.stderr, flush=True)
        log_path = logs / f"{stage}.log"
        with log_path.open("w", encoding="utf-8") as log:
            code = run_owner(command, [str(arg) for arg in arguments], log=log)
        if code:
            raise ValueError(f"{stage} failed (exit {code}); read {log_path}. Retained files: {destination}")

    execute("capture-check", "capture", ["check"])
    sample = destination / "sample"
    with (logs / "init.log").open("w", encoding="utf-8") as log, redirect_stdout(log):
        initialize(sample)
    story = sample / ("promo.json" if mode == "promo" else "feature.json")
    execute("story", "story", ["--request", sample / "request.json", "--story", story,
                               "--brand-dir", sample / "brand", "--out", destination / "story-plan"])

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(sample / "taskboard")))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    take = None
    session_path = None
    session = None
    steps = {}
    proofs = []
    try:
        capture_source = "motion-capture.json" if mode == "promo" else "capture.json"
        script = json.loads((sample / capture_source).read_text())
        if mode == "promo" and script.get("viewport") != {"width": 3840, "height": 2160}:
            raise ValueError("promo capture must use the bundled 3840x2160 motion recipe")
        script["url"] = f"http://127.0.0.1:{server.server_port}/"
        capture = destination / capture_source
        capture.write_text(json.dumps(script, indent=2) + "\n")
        execute("capture-validate", "capture", ["validate", capture])
        execute("capture", "capture", ["rec", capture, "--out-dir", destination / "takes", "--no-burn-captions"])

        sessions = list((destination / "takes").glob("*/session.json"))
        if len(sessions) != 1:
            raise ValueError(f"expected one recorded take; inspect {destination / 'takes'}")
        session_path = sessions[0]
        take = session_path.parent
        session = json.loads(session_path.read_text())
        steps = session.get("steps", {})
        proofs = session.get("assertions", [])
        expected = sum(step["do"] == "assert" for step in script["steps"])
        if (not steps.get("total") or steps.get("ok") != steps["total"]
                or len(proofs) != expected or session.get("streams", {}).get("screen", {}).get("status") != "ok"):
            raise ValueError(f"capture result is incomplete; inspect {session_path}")
        for proof in proofs:
            screenshot = (take / proof.get("screenshot", "")).resolve()
            if (proof.get("status") != "passed" or not screenshot.is_relative_to(take)
                    or not screenshot.is_file() or hashlib.sha256(screenshot.read_bytes()).hexdigest() != proof.get("sha256")):
                raise ValueError(f"capture result evidence failed verification; inspect {session_path}")
        if mode == "promo":
            if expected != 4:
                raise ValueError(f"promo capture must retain four assertions; inspect {session_path}")
            stage = "prepare-motion"
            log_path = logs / f"{stage}.log"
            print(f"taskfilm demo: {stage}", file=sys.stderr, flush=True)
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    prepared = subprocess.run(
                        [sys.executable, str(sample / "prepare-motion.py"), "--sample", str(sample),
                         "--take", str(take), "--url", script["url"]],
                        stdout=log, stderr=subprocess.STDOUT)
            except OSError as exc:
                raise ValueError(f"{stage} failed; read {log_path}. Retained files: {destination}") from exc
            if prepared.returncode:
                raise ValueError(f"{stage} failed (exit {prepared.returncode}); read {log_path}. Retained files: {destination}")
            try:
                json.loads(log_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(f"{stage} returned invalid JSON; read {log_path}. Retained files: {destination}") from exc
            if not (sample / "spec.json").is_file():
                raise ValueError(f"{stage} did not create spec.json; read {log_path}. Retained files: {destination}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert take is not None and session_path is not None

    if mode == "promo":
        formats = ["landscape", "portrait"] if format == "both" else [format]
        deliverables = []
        for requested_format in formats:
            execute(f"motion-{requested_format}", "motion",
                    [sample, "--format", requested_format, "--take", take])
            composition = sample / "cuts" / requested_format
            edit_decisions = composition / "EDIT-DECISIONS.json"
            required = [composition / "index.html", composition / "hyperframes.json", edit_decisions]
            if not all(path.is_file() for path in required):
                raise ValueError(f"motion-{requested_format} produced incomplete output; inspect {composition}")
            movie = destination / f"promo-{requested_format}.mp4"
            if render:
                print(f"taskfilm demo: render-{requested_format}", file=sys.stderr, flush=True)
                with (logs / f"render-{requested_format}.log").open("w", encoding="utf-8") as log:
                    code = render_project(composition, movie, quality, log=log)
                if code or not movie.is_file() or movie.stat().st_size == 0:
                    raise ValueError(f"render-{requested_format} failed; read {logs / f'render-{requested_format}.log'}")
            deliverables.append({"format": requested_format, "composition": str(composition),
                                 "edit_decisions": str(edit_decisions), "rendered": render,
                                 "movie": str(movie) if render else None,
                                 "movie_sha256": hashlib.sha256(movie.read_bytes()).hexdigest() if render else None})
        primary = deliverables[0]
        report = {"schema": "taskfilm-demo/v1", "destination": str(destination), "mode": mode,
                  "formats": formats, "take": str(take), "session": str(session_path),
                  "composition": primary["composition"], "steps": steps,
                  "assertions_verified": len(proofs), "assertions": proofs,
                  "session_sha256": hashlib.sha256(session_path.read_bytes()).hexdigest(),
                  "server_stopped": True,
                  "rendered": render, "final_video_review": "not_performed",
                  "movie": primary["movie"], "movie_sha256": primary["movie_sha256"],
                  "deliverables": deliverables, "report": str(destination / "DEMO-RESULT.json")}
        (destination / "DEMO-RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
        return report

    execute("edit", "edit", [take, "--no-retime", "--no-aim"])
    composition = destination / "composition"
    execute("compose", "compose", [take, "--out", composition, "--no-title", "--width", 1280,
                                   "--height", 720, "--max-scale", 1, "--note-top", 4])
    movie = destination / "lesson.mp4"
    if render:
        print("taskfilm demo: render", file=sys.stderr, flush=True)
        with (logs / "render.log").open("w", encoding="utf-8") as log:
            code = render_project(composition, movie, quality, log=log)
        if code or not movie.is_file() or movie.stat().st_size == 0:
            raise ValueError(f"render failed; read {logs / 'render.log'}. Editable project: {composition}")

    report = {"schema": "taskfilm-demo/v1", "destination": str(destination),
              "take": str(take), "session": str(session_path), "composition": str(composition),
              "steps": steps, "assertions_verified": len(proofs), "server_stopped": True,
              "rendered": render, "final_video_review": "not_performed",
              "movie": str(movie) if render else None,
              "movie_sha256": hashlib.sha256(movie.read_bytes()).hexdigest() if render else None,
              "next": ["Edit composition/index.html to customize the lesson.",
                       "taskfilm render composition --output my-film.mp4 (run from the demo directory).",
                       "Review the finished movie before sharing."],
              "report": str(destination / "DEMO-RESULT.json")}
    (destination / "DEMO-RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
