"""Produce a course through the existing capture, polish and render owners.

The agent authors the curriculum and scripts from the teacher's sources. This
owner keeps those decisions editable, resumes individual lessons, and packages
actual films without treating preparation or media checks as a human review.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

VIDEO = Path(__file__).resolve().parents[1]
SCHEMA = "taskfilm-course/v1"
ENGINE = "course-1"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value) -> None:
    """Publish state only after a complete write; leave the old state on failure."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".course-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value.strip()


def validate(course: dict) -> dict:
    if not isinstance(course, dict) or course.get("schema") != SCHEMA:
        raise ValueError(f"course schema must be {SCHEMA}")
    for field in ("title", "audience", "language"):
        text(course.get(field), field)
    lessons = course.get("lessons")
    if not isinstance(lessons, list) or not 1 <= len(lessons) <= 150:
        raise ValueError("a course needs 1–150 ordered lessons")
    ids = set()
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("each lesson must be an object")
        identity = lesson.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identity):
            raise ValueError("lesson id must use lowercase letters, digits and hyphens, starting with a letter")
        if identity in ids:
            raise ValueError(f"duplicate lesson id: {identity}")
        ids.add(identity)
        for field in ("module", "title", "objective", "exercise", "success_criteria"):
            text(lesson.get(field), f"{identity}.{field}")
        for field in ("source", "capture", "voiceover"):
            if lesson.get(field) is not None and not isinstance(lesson[field], str):
                raise ValueError(f"{identity}.{field} must be a file path")
        if lesson.get("source") and lesson.get("capture"):
            raise ValueError(f"{identity}: choose a source recording or a capture script")
        resources = lesson.get("resources", [])
        if not isinstance(resources, list):
            raise ValueError(f"{identity}.resources must be a list")
        for resource in resources:
            if not isinstance(resource, dict):
                raise ValueError("each resource needs title and path")
            text(resource.get("title"), "resource.title")
            text(resource.get("path"), "resource.path")
    return course


def local(home: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (home / path).resolve() if not path.is_absolute() else path.resolve()


def owned(home: Path, value: str) -> Path:
    path = local(home, value)
    if not path.is_relative_to(home.resolve()):
        raise ValueError("generated course paths must stay inside the course")
    return path


def folder(home: Path, lesson: dict) -> Path:
    return owned(home, f"lessons/{lesson['id']}")


def load(home: Path) -> dict:
    return validate(read(home / "course.json"))


def initialize(outline: Path, destination: Path) -> dict:
    course = validate(read(outline))
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("course destination must be a new directory")
    # Normalize imported paths before moving the outline into its workspace.
    for lesson in course["lessons"]:
        for field in ("source", "capture", "voiceover"):
            if lesson.get(field):
                lesson[field] = str(local(outline.resolve().parent, lesson[field]))
        for resource in lesson.get("resources", []):
            resource["path"] = str(local(outline.resolve().parent, resource["path"]))
        if "script" in lesson and not isinstance(lesson["script"], str):
            raise ValueError("lesson script must be text")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".course-init-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "course"
        stage.mkdir()
        for lesson in course["lessons"]:
            here = folder(stage, lesson)
            here.mkdir(parents=True)
            (here / "script.txt").write_text(lesson.pop("script", ""), encoding="utf-8")
            (here / "instructor-notes.txt").write_text("", encoding="utf-8")
            write(here / "edits.json", {"schema": "taskfilm-polish/v1", "preset": "studio",
                                       "audio": "keep", "cuts": [], "speed": [],
                                       "zooms": [], "annotations": []})
        write(stage / "course.json", course)
        (stage / "START-HERE.txt").write_text(
            "Edit course.json to refine the curriculum, sources and exercises.\n"
            "Each lessons/ID folder keeps script.txt, instructor-notes.txt and edits.json.\n"
            "Add a personal recording: taskfilm course voiceover . --lesson ID --audio FILE\n"
            "Voiceover starts at source time zero; source-time cuts affect voice and picture together.\n"
            "taskfilm course build . --prepare-only prepares editable HyperFrames projects.\n"
            "taskfilm course build . renders the films and resumes unchanged lessons.\n"
            "taskfilm course status . reports what needs attention.\n"
            "taskfilm course package . --out course.zip collects current films and learner guides.\n"
            "Scripts are teaching notes; editing text does not synthesize or replace recorded speech.\n",
            encoding="utf-8")
        # mkdir reserves the name without replacing an existing course.
        destination.mkdir()
        for item in stage.iterdir():
            item.rename(destination / item.name)
    return {"course": str(destination), "lessons": len(course["lessons"]), "execution": "planned_only"}


def source_file(home: Path, lesson: dict) -> Path | None:
    if lesson.get("source"):
        return local(home, lesson["source"])
    state = folder(home, lesson) / "capture-state.json"
    if lesson.get("capture") and state.is_file():
        saved = read(state)
        script = local(home, lesson["capture"])
        source = owned(home, saved["source"])
        if (script.is_file() and saved["script_sha256"] == sha256(script)
                and source.is_file() and saved["source_sha256"] == sha256(source)):
            return source
    return None


def inputs(home: Path, course: dict, lesson: dict) -> tuple[str, list[str]]:
    files = {"script": folder(home, lesson) / "script.txt",
             "edits": folder(home, lesson) / "edits.json",
             "instructor_notes": folder(home, lesson) / "instructor-notes.txt"}
    source = source_file(home, lesson)
    if lesson.get("capture"):
        files["capture"] = local(home, lesson["capture"])
    if source:
        files["source"] = source
    if lesson.get("voiceover"):
        files["voiceover"] = local(home, lesson["voiceover"])
        if lesson.get("voiceover_kind") == "ai":
            files["voice_receipt"] = files["voiceover"].parent / "NARRATION.json"
    for i, resource in enumerate(lesson.get("resources", [])):
        files[f"resource_{i}"] = local(home, resource["path"])
    missing = [f"Missing {key}: {path}" for key, path in files.items() if not path.is_file()]
    if not lesson.get("source") and not lesson.get("capture"):
        missing.append(f"Add a source recording or browser capture path for {lesson['id']} in course.json")
    if files["script"].is_file() and not files["script"].read_text(encoding="utf-8-sig").strip():
        missing.append("Write the lesson script in script.txt")
    if (lesson.get("voiceover_kind") == "ai" and files["script"].is_file()
            and files["voice_receipt"].is_file() and files["voiceover"].is_file()):
        receipt = read(files["voice_receipt"])
        script_hash = hashlib.sha256(files["script"].read_text(encoding="utf-8-sig").strip().encode()).hexdigest()
        if (receipt.get("script_sha256") != script_hash or receipt.get("language") != course["language"]
                or receipt.get("audio_sha256") != sha256(files["voiceover"])):
            missing.append("AI narration no longer matches this lesson; run course narrate again")
    payload = {"engine": ENGINE, "course": {k: v for k, v in course.items() if k != "lessons"},
               "lesson": lesson, "files": {key: sha256(path) for key, path in files.items() if path.is_file()}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), missing


def project_hash(project: Path) -> str:
    files = {path.relative_to(project).as_posix(): sha256(path)
             for path in sorted(project.rglob("*")) if path.is_file()
             and not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(project).parts)}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def state_for(home: Path, lesson: dict) -> dict | None:
    path = folder(home, lesson) / "current.json"
    return read(path) if path.is_file() else None


def lesson_status(home: Path, course: dict, lesson: dict) -> dict:
    fingerprint, problems = inputs(home, course, lesson)
    current = state_for(home, lesson)
    result = {"id": lesson["id"], "module": lesson["module"], "title": lesson["title"],
              "state": "blocked" if problems else "pending", "problems": problems,
              "review": "not_reviewed", "fingerprint": fingerprint}
    if problems or not current:
        return result
    project = owned(home, current["project"])
    if current["fingerprint"] != fingerprint or not (project / "index.html").is_file():
        result["state"] = "stale"
        return result
    if current["project_sha256"] != project_hash(project):
        result["state"] = "edited"
        return result
    result["project"] = str(project)
    if not current.get("movie"):
        result["state"] = "prepared"
        return result
    movie = owned(home, current["movie"])
    if not movie.is_file() or sha256(movie) != current["movie_sha256"]:
        result["state"] = "stale"
        return result
    result.update(state="rendered", movie=str(movie), movie_sha256=current["movie_sha256"], duration_s=current["qa"]["duration_s"],
                  audio=current["qa"]["audio"], warnings=current["qa"]["warnings"])
    review_file = folder(home, lesson) / "review.json"
    if review_file.is_file():
        review = read(review_file)
        if review.get("fingerprint") == fingerprint and review.get("movie_sha256") == current["movie_sha256"]:
            result["review"] = "reviewed"
    return result


def status(home: Path) -> dict:
    home = home.resolve()
    course = load(home)
    lessons = []
    for lesson in course["lessons"]:
        try:
            lessons.append(lesson_status(home, course, lesson))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            lessons.append({"id": lesson["id"], "state": "blocked", "problems": [str(exc)]})
    return {"schema": SCHEMA, "title": course["title"], "lessons": lessons,
            "rendered": sum(row["state"] == "rendered" for row in lessons), "total": len(lessons),
            "ready_to_package": all(row["state"] == "rendered" for row in lessons)}


def owners():
    if str(VIDEO) not in sys.path:
        sys.path.insert(0, str(VIDEO))
    import videokit
    return videokit.load("capturelane.polish"), videokit.load("editlane.course_delivery")


def command(args: list[str], log: Path, *, cwd: Path | None = None, timeout=1800) -> None:
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(args, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Command failed; see {log}")


def capture(home: Path, lesson: dict, run: Path) -> Path:
    script = local(home, lesson["capture"])
    script_hash = sha256(script)
    spec = read(script)
    steps = spec.get("steps", []) if isinstance(spec, dict) else []
    if not isinstance(steps, list) or not any(isinstance(step, dict) and step.get("do") == "assert" for step in steps):
        raise ValueError("A course capture needs a visible-result assert step")
    takes = run / "takes"
    command([sys.executable, str(VIDEO / "capture-lane/webrec.py"), "rec", str(script),
             "--out-dir", str(takes), "--no-burn-captions"], run / "capture.log", cwd=script.parent)
    sessions = list(takes.glob("*/session.json"))
    if len(sessions) != 1:
        raise ValueError("Capture did not produce one unique take")
    session = read(sessions[0])
    assertions = session.get("assertions", [])
    if not assertions or any(row.get("status") != "passed" for row in assertions):
        raise ValueError("The recorded lesson did not pass its visible-result checks")
    for assertion in assertions:
        screenshot = owned(home, str(sessions[0].parent / assertion["screenshot"]))
        if not screenshot.is_file() or sha256(screenshot) != assertion["sha256"]:
            raise ValueError("The recorded result screenshot does not match its evidence hash")
    if sha256(script) != script_hash:
        raise ValueError("Capture script changed while recording; keep the take and record again")
    source = owned(home, str(sessions[0].parent / session["streams"]["screen"]["path"]))
    if not source.is_file():
        raise ValueError("The capture did not produce a recording")
    write(folder(home, lesson) / "capture-state.json",
          {"script_sha256": script_hash, "source": str(source.relative_to(home)),
           "source_sha256": sha256(source), "session": str(sessions[0].relative_to(home))})
    return source


def qa(movie: Path, expected: dict, delivery, log: Path) -> dict:
    media = delivery.probe(movie)
    if not media["video"] or abs(media["duration"] - expected["duration"]) > .3:
        raise ValueError("The lesson film's duration or video stream does not match its edit")
    if expected["audio_retained"] and not media["audio"]:
        raise ValueError("The lesson film lost its narration audio")
    command(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-threads", "1", "-i", str(movie),
             "-f", "null", "-"], log)
    return {"decode": "passed", "duration_s": media["duration"], "audio": media["audio"],
            "timing_source": expected.get("timing_source", "edit_specification"),
            "warnings": [] if media["audio"] else ["Silent lesson: add a voiceover or a narrated recording"],
            "teaching_accuracy": "not_reviewed", "audio_action_sync": "not_reviewed"}


def edited_timeline(project: Path, run: Path, version: str) -> dict:
    """Read the editor's current timing through HyperFrames' metadata contract."""
    result = subprocess.run(["npx", "--yes", f"hyperframes@{version}", "timeline", "--json"],
                            cwd=project, capture_output=True, text=True, timeout=120)
    (run / "timeline.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"Cannot read the edited timeline; see {run / 'timeline.log'}")
    data = json.loads(result.stdout)
    duration = data.get("timeline", {}).get("duration")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("The edited timeline needs a positive, finite duration")
    write(run / "TIMELINE.json", data)
    audio = any(track.get("kind") == "audio" and track.get("rows")
                for track in data["timeline"].get("tracks", []))
    return {"duration": duration, "audio_retained": audio, "timing_source": "edited_project"}


def build(home: Path, *, lesson_id: str | None = None, prepare_only=False, quality="looks", recapture=False) -> dict:
    home = home.resolve()
    course = load(home)
    selected = [row for row in course["lessons"] if lesson_id is None or row["id"] == lesson_id]
    if not selected:
        raise ValueError(f"Unknown lesson: {lesson_id}")
    polish, delivery = owners()
    results = []
    for lesson in selected:
        run = None
        editing_source = None
        editing_source_hash = None
        timeline_edited = False
        try:
            before = lesson_status(home, course, lesson)
            if before["problems"]:
                raise ValueError("; ".join(before["problems"]))
            previous = state_for(home, lesson)
            record_again = recapture and bool(lesson.get("capture"))
            if not record_again and (before["state"] == "rendered" and previous.get("quality") == quality
                    or prepare_only and before["state"] in {"prepared", "rendered", "edited"}):
                results.append({"id": lesson["id"], "state": before["state"], "reused": True})
                continue
            run = folder(home, lesson) / "builds" / uuid.uuid4().hex[:12]
            run.mkdir(parents=True)
            project = run / "project"
            fingerprint = before["fingerprint"]
            if not record_again and previous and previous["fingerprint"] == before["fingerprint"] and before["state"] in {"prepared", "rendered", "edited"}:
                # A teacher's edits in the prepared project are the next render's input.
                editing_source = owned(home, previous["project"])
                editing_source_hash = project_hash(editing_source)
                shutil.copytree(editing_source, project,
                                ignore=shutil.ignore_patterns("node_modules", ".git", ".hyperframes"))
                if project_hash(project) != editing_source_hash:
                    raise ValueError("Editable project changed while copying; run build again")
                prepared = read(project / "POLISH.json")
                timeline_edited = before["state"] == "edited" or previous.get("timeline_edited", False)
            else:
                source = None if record_again else source_file(home, lesson)
                if source is None:
                    source = capture(home, lesson, run)
                fingerprint, problems = inputs(home, course, lesson)
                if problems:
                    raise ValueError("; ".join(problems))
                if lesson.get("voiceover"):
                    voice = local(home, lesson["voiceover"])
                    shutil.copy2(source, run / ("original-source" + source.suffix))
                    shutil.copy2(voice, run / ("instructor-voice" + voice.suffix))
                    narrated = run / "narrated-source.mp4"
                    delivery.deliver(source, narrated, voice=voice)
                    source = narrated
                with redirect_stdout(sys.stderr):
                    prepared = polish.create(source, project, read(folder(home, lesson) / "edits.json"))
            if timeline_edited:
                prepared.update(edited_timeline(project, run, polish.hfcomp.HYPERFRAMES_VERSION))
            state = {"fingerprint": fingerprint, "project": str(project.relative_to(home)),
                     "project_sha256": project_hash(project), "movie": None, "quality": quality,
                     "timeline_edited": timeline_edited}
            if not prepare_only:
                movie = run / "lesson.mp4"
                command([sys.executable, "-m", "taskfilm", "render", str(project), "--output", str(movie),
                         "--quality", quality], run / "render.log")
                if project_hash(project) != state["project_sha256"]:
                    raise ValueError("Editable project changed during rendering; the edits were kept. Run build again")
                state.update(movie=str(movie.relative_to(home)), movie_sha256=sha256(movie),
                             qa=qa(movie, prepared, delivery, run / "decode.log"),
                             project_sha256=project_hash(project))
            # Never bless a movie made from inputs that changed during a render.
            refreshed = load(home)
            refreshed_lesson = next((row for row in refreshed["lessons"] if row["id"] == lesson["id"]), None)
            if refreshed_lesson is None:
                raise ValueError("Lesson was removed during production; old outputs were kept")
            after, problems = inputs(home, refreshed, refreshed_lesson)
            if problems or after != fingerprint:
                raise ValueError("Lesson inputs changed during production; old outputs were kept. Run build again.")
            if editing_source and project_hash(editing_source) != editing_source_hash:
                raise ValueError("Instructor edited the previous project during production; run build again to include those edits")
            write(run / "BUILD.json", state)
            write(folder(home, lesson) / "current.json", state)
            results.append({"id": lesson["id"], "state": "prepared" if prepare_only else "rendered", "reused": False,
                            "project": str(project), "movie": str(owned(home, state["movie"])) if state["movie"] else None})
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            error = {"id": lesson["id"], "state": "failed", "error": str(exc)}
            if run:
                error["build"] = str(run)
                write(run / "FAILURE.json", error)
            results.append(error)
    report = {"schema": SCHEMA, "lessons": results, "ok": all(row["state"] != "failed" for row in results),
              "execution": "planned_only" if prepare_only else "rendered" if all(row["state"] == "rendered" for row in results) else "incomplete"}
    write(home / "BUILD-RESULT.json", report)
    return report


def voiceover(home: Path, lesson_id: str, audio: Path) -> dict:
    home = home.resolve()
    course = load(home)
    lesson = next((row for row in course["lessons"] if row["id"] == lesson_id), None)
    if lesson is None:
        raise ValueError(f"Unknown lesson: {lesson_id}")
    _, delivery = owners()
    if not delivery.probe(audio)["audio"]:
        raise ValueError("The personal voiceover must contain an audio stream")
    target = folder(home, lesson) / "voiceovers" / (uuid.uuid4().hex[:12] + audio.suffix.lower())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio, target)
    if sha256(target) != sha256(audio):
        raise ValueError("Voiceover changed while importing; choose a stable recording")
    course = load(home)
    lesson = next(row for row in course["lessons"] if row["id"] == lesson_id)
    lesson["voiceover"] = str(target.relative_to(home))
    lesson["voiceover_kind"] = "human"
    write(home / "course.json", course)
    return {"lesson": lesson_id, "voiceover": str(target), "alignment": "source_time_zero", "rebuild_required": True}


def narrate(home: Path, voice_id: str, *, lesson_id: str | None = None, replace=False) -> dict:
    """Opt-in AI narration uses one supplied key; personal recordings take priority."""
    home = home.resolve()
    course = load(home)
    selected = [row for row in course["lessons"] if lesson_id is None or row["id"] == lesson_id]
    if not selected:
        raise ValueError(f"Unknown lesson: {lesson_id}")
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise ValueError("AI narration needs your own ELEVENLABS_API_KEY environment variable")
    text(voice_id, "voice id")
    owners()
    import videokit
    narration = videokit.load("editlane.course_narration")
    results = []
    for lesson in selected:
        script = (folder(home, lesson) / "script.txt").read_text(encoding="utf-8-sig")
        if lesson.get("voiceover") and not replace:
            audio = local(home, lesson["voiceover"])
            receipt_path = audio.parent / "NARRATION.json"
            if lesson.get("voiceover_kind") != "ai":
                results.append({"id": lesson["id"], "state": "voiceover_kept"})
                continue
            if audio.is_file() and receipt_path.is_file():
                saved = read(receipt_path)
                script_hash = hashlib.sha256(script.strip().encode()).hexdigest()
                if (saved.get("script_sha256") == script_hash and saved.get("voice_id") == voice_id
                        and saved.get("language") == course["language"] and saved.get("audio_sha256") == sha256(audio)):
                    results.append({"id": lesson["id"], "state": "voiceover_kept"})
                    continue
        target = folder(home, lesson) / "voiceovers" / uuid.uuid4().hex[:12]
        try:
            receipt = narration.narrate(script, target, key=key, voice=voice_id, language=course["language"])
            current_script = (folder(home, lesson) / "script.txt").read_text(encoding="utf-8-sig").strip()
            if hashlib.sha256(current_script.encode()).hexdigest() != receipt["script_sha256"]:
                raise ValueError("Script changed during narration; the read was kept. Run narrate again")
            course = load(home)
            lesson = next(row for row in course["lessons"] if row["id"] == lesson["id"])
            if course["language"] != receipt["language"]:
                raise ValueError("Course language changed during narration; the read was kept")
            lesson["voiceover"] = str(Path(receipt["audio"]).relative_to(home))
            lesson["voiceover_kind"] = "ai"
            write(home / "course.json", course)
            results.append({"id": lesson["id"], "state": "narrated", "audio": receipt["audio"]})
        except (ValueError, OSError) as exc:
            results.append({"id": lesson["id"], "state": "failed", "error": str(exc)})
    return {"lessons": results, "ok": all(row["state"] != "failed" for row in results)}


def review(home: Path, lesson_id: str, reviewer: str, *, confirmed=False) -> dict:
    if not confirmed:
        raise ValueError("Review requires --confirm-reviewed after watching and listening to the actual film")
    home = home.resolve()
    course = load(home)
    lesson = next((row for row in course["lessons"] if row["id"] == lesson_id), None)
    if lesson is None:
        raise ValueError(f"Unknown lesson: {lesson_id}")
    current_status = lesson_status(home, course, lesson)
    if current_status["state"] != "rendered":
        raise ValueError("Render the current lesson before recording a review")
    event = {"reviewer": text(reviewer, "reviewer"), "at": datetime.now(timezone.utc).isoformat(),
             "fingerprint": current_status["fingerprint"], "movie_sha256": current_status["movie_sha256"],
             "declaration": "Caller confirms watching and listening to this exact lesson"}
    write(folder(home, lesson) / "review.json", event)
    return event


def learner_guide(course: dict, lesson: dict, script: str) -> str:
    resources = "\n".join(f"- {row['title']}" for row in lesson.get("resources", []))
    return (f"{course['title']}\n{lesson['module']} / {lesson['title']}\n\n"
            f"Learning objective\n{lesson['objective']}\n\nLesson script\n{script.strip()}\n\n"
            f"Practice\n{lesson['exercise']}\n\nCheck your result\n{lesson['success_criteria']}\n\n"
            f"Resources\n{resources or 'No additional files needed.'}\n")


def archive_file(archive, source: Path, name: str, expected: str) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle, archive.open(name, "w", force_zip64=True) as target:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            target.write(block)
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("Course media changed while packaging; rebuild before delivery")
    return digest.hexdigest()


def package(home: Path, output: Path) -> dict:
    home, output = home.resolve(), output.absolute()
    report, course = status(home), load(home)
    if not report["ready_to_package"]:
        pending = ", ".join(f"{row['id']}: {row['state']}" for row in report["lessons"] if row["state"] != "rendered")
        raise ValueError(f"Build current lesson films before packaging: {pending}")
    if output.exists() or output.is_symlink():
        raise ValueError("package output must be a new file")
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = []
    with tempfile.TemporaryDirectory(prefix=".course-package-", dir=output.parent) as temporary:
        archive_path = Path(temporary) / "course.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("START-HERE.txt", f"{course['title']}\nFor: {course['audience']}\nLanguage: {course['language']}\n\n"
                             "Follow the numbered lesson folders in order. Each contains a film and a practice guide.\n"
                             "COURSE.json records media checks and declared instructor reviews separately.\n")
            for index, (lesson, checked) in enumerate(zip(course["lessons"], report["lessons"]), 1):
                prefix = f"{index:03d}-{lesson['id']}"
                movie = Path(checked["movie"])
                digest = archive_file(archive, movie, f"{prefix}/lesson.mp4", checked["movie_sha256"])
                script = (folder(home, lesson) / "script.txt").read_text(encoding="utf-8-sig")
                archive.writestr(f"{prefix}/learner-guide.txt", learner_guide(course, lesson, script))
                resources = []
                for i, resource in enumerate(lesson.get("resources", []), 1):
                    source = local(home, resource["path"])
                    name = f"{prefix}/resources/{i:02d}-{source.name}"
                    resource_hash = archive_file(archive, source, name, sha256(source))
                    resources.append({"title": resource["title"], "file": name, "sha256": resource_hash})
                inventory.append({"id": lesson["id"], "module": lesson["module"], "title": lesson["title"],
                                  "movie": f"{prefix}/lesson.mp4", "movie_sha256": digest,
                                  "duration_s": checked["duration_s"], "review": checked["review"],
                                  "warnings": checked["warnings"], "resources": resources})
            manifest = {"schema": SCHEMA, "title": course["title"], "audience": course["audience"],
                        "language": course["language"], "lessons": inventory, "media_decode": "passed",
                        "instructor_review": "reviewed" if all(row["review"] == "reviewed" for row in inventory) else "pending"}
            archive.writestr("COURSE.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        current = status(home)
        if not current["ready_to_package"] or current["lessons"] != report["lessons"]:
            raise ValueError("Course changed while packaging; run package again with stable lesson inputs")
        # Exclusive creation preserves any existing delivery, including a racing writer.
        os.link(archive_path, output)
    return {"package": str(output), "sha256": sha256(output), "lessons": len(inventory),
            "instructor_review": manifest["instructor_review"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="taskfilm course", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create an editable course from a curriculum JSON")
    init.add_argument("destination", type=Path)
    init.add_argument("--outline", required=True, type=Path)
    check = commands.add_parser("status", help="show current lesson films, missing inputs and human edits")
    check.add_argument("course", type=Path)
    make = commands.add_parser("build", help="produce lessons; resume current films and retain old takes")
    make.add_argument("course", type=Path)
    make.add_argument("--lesson")
    make.add_argument("--prepare-only", action="store_true")
    make.add_argument("--quality", choices=("draft", "looks", "delivery"), default="looks")
    make.add_argument("--recapture", action="store_true", help="record fresh browser takes after the target application changes")
    voice = commands.add_parser("voiceover", help="attach the instructor's own audio without losing prior reads")
    voice.add_argument("course", type=Path)
    voice.add_argument("--lesson", required=True)
    voice.add_argument("--audio", required=True, type=Path)
    speech = commands.add_parser("narrate", help="generate optional AI reads with your own ElevenLabs key")
    speech.add_argument("course", type=Path)
    speech.add_argument("--lesson")
    speech.add_argument("--voice-id", required=True)
    speech.add_argument("--replace", action="store_true", help="explicitly replace an attached read; old audio is retained")
    approve = commands.add_parser("review", help="record an explicit review of the exact current lesson")
    approve.add_argument("course", type=Path)
    approve.add_argument("--lesson", required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--confirm-reviewed", action="store_true")
    deliver = commands.add_parser("package", help="collect current films, exercises and practice resources into a ZIP")
    deliver.add_argument("course", type=Path)
    deliver.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.outline, args.destination)
        elif args.command == "status":
            result = status(args.course)
        elif args.command == "build":
            result = build(args.course, lesson_id=args.lesson, prepare_only=args.prepare_only, quality=args.quality, recapture=args.recapture)
        elif args.command == "voiceover":
            result = voiceover(args.course, args.lesson, args.audio)
        elif args.command == "narrate":
            result = narrate(args.course, args.voice_id, lesson_id=args.lesson, replace=args.replace)
        elif args.command == "review":
            result = review(args.course, args.lesson, args.reviewer, confirmed=args.confirm_reviewed)
        else:
            result = package(args.course, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("ok") is False else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"taskfilm course: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
