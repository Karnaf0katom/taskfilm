"""Course production checks use real local media; paid voice calls are injected."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from taskfilm.cli import VIDEO

spec = importlib.util.spec_from_file_location("taskfilm_course_tests", VIDEO / "director/course.py")
course = importlib.util.module_from_spec(spec)
spec.loader.exec_module(course)


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def source(tmp_path):
    movie = tmp_path / "owned recording.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=15:duration=2", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=2", "-c:v", "libx264", "-threads", "1",
                    "-filter_threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", str(movie)],
                   check=True, capture_output=True, timeout=30)
    return movie


@pytest.fixture
def workspace(tmp_path, source):
    outline = tmp_path / "outline.json"
    lessons = [{"id": identity, "module": "Practice", "title": identity, "objective": "Recognize a visible result",
                "script": "Inspect the real recording, perform the task and check the result.",
                "exercise": "Repeat the task", "success_criteria": "The expected result is visible",
                "source": source.name, "resources": []} for identity in ("start", "finish")]
    dump(outline, {"schema": course.SCHEMA, "title": "An owned test course", "audience": "Test learners",
                   "language": "en", "lessons": lessons})
    home = tmp_path / "my course"
    course.initialize(outline, home)
    for identity in ("start", "finish"):
        dump(home / f"lessons/{identity}/edits.json", {"width": 320, "height": 240,
             "style": {"padding": 0, "radius": 0, "shadow": False}, "audio": "keep"})
    return home


def test_init_preserves_curriculum_and_never_overwrites(workspace, tmp_path):
    state = course.load(workspace)
    assert [row["id"] for row in state["lessons"]] == ["start", "finish"]
    assert Path(state["lessons"][0]["source"]).is_absolute()
    script = workspace / "lessons/start/script.txt"
    script.write_text("My own example", encoding="utf-8")
    with pytest.raises(ValueError, match="new directory"):
        course.initialize(tmp_path / "outline.json", workspace)
    assert script.read_text() == "My own example"


@pytest.mark.parametrize("identity", ["../outside", "one/../../outside", "UPPER", "", "/absolute"])
def test_unsafe_lesson_ids_are_rejected(workspace, identity):
    outline = course.load(workspace)
    outline["lessons"][0]["id"] = identity
    with pytest.raises(ValueError, match="lesson id"):
        course.validate(outline)


def test_duplicate_ids_and_unteachable_outlines_fail(workspace):
    outline = course.load(workspace)
    outline["lessons"][1]["id"] = "start"
    with pytest.raises(ValueError, match="duplicate"):
        course.validate(outline)
    outline["lessons"].pop()
    outline["lessons"][0]["success_criteria"] = " "
    with pytest.raises(ValueError, match="success_criteria"):
        course.validate(outline)


def test_cli_forwards_course_help(tmp_path):
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "course", "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert all(word in result.stdout for word in ("build", "narrate", "voiceover", "package"))


def test_prepared_lessons_are_editable_and_not_packaged_as_films(workspace, tmp_path):
    result = course.build(workspace, prepare_only=True)
    assert result["ok"] and result["execution"] == "planned_only"
    checked = course.status(workspace)
    assert checked["rendered"] == 0 and not checked["ready_to_package"]
    assert {row["state"] for row in checked["lessons"]} == {"prepared"}
    current = course.state_for(workspace, {"id": "start"})
    project = workspace / current["project"]
    assert (project / "index.html").is_file()
    assert (project / "original/recording.mp4").is_file()
    assert (project / "assets/source-audio.wav").is_file()
    with pytest.raises(ValueError, match="before packaging"):
        course.package(workspace, tmp_path / "refused.zip")
    assert not (tmp_path / "refused.zip").exists()
    with pytest.raises(ValueError, match="Render the current"):
        course.review(workspace, "start", "Test", confirmed=True)


def test_prepare_resumes_and_keeps_human_edits(workspace):
    course.build(workspace, prepare_only=True)
    current = course.state_for(workspace, {"id": "start"})
    project = workspace / current["project"]
    html = project / "index.html"
    html.write_text(html.read_text() + "\n<!-- personal teaching example -->\n")
    script = workspace / "lessons/finish/script.txt"
    script.write_text("My revised explanation", encoding="utf-8")
    results = course.build(workspace, prepare_only=True)
    assert results["lessons"][0] == {"id": "start", "state": "edited", "reused": True}
    assert not results["lessons"][1]["reused"]
    assert "personal teaching example" in html.read_text()
    assert script.read_text() == "My revised explanation"
    assert course.state_for(workspace, {"id": "start"}) == current


def test_one_blocked_lesson_does_not_discard_other_preparations(workspace):
    (workspace / "lessons/start/script.txt").write_text("")
    result = course.build(workspace, prepare_only=True)
    assert not result["ok"]
    assert [row["state"] for row in result["lessons"]] == ["failed", "prepared"]
    assert "Write the lesson script" in result["lessons"][0]["error"]


def test_voiceover_keeps_previous_reads_and_invalidates_only_its_lesson(workspace, source, tmp_path):
    course.build(workspace, prepare_only=True)
    voice = tmp_path / "personal voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-map", "0:a:0", str(voice)],
                   check=True, capture_output=True, timeout=30)
    first = course.voiceover(workspace, "start", voice)
    second = course.voiceover(workspace, "start", voice)
    assert first["voiceover"] != second["voiceover"]
    assert Path(first["voiceover"]).read_bytes() == voice.read_bytes()
    assert [row["state"] for row in course.status(workspace)["lessons"]] == ["stale", "prepared"]
    result = course.build(workspace, prepare_only=True)
    assert result["ok"] and result["lessons"][1]["reused"]
    state = course.state_for(workspace, {"id": "start"})
    run = (workspace / state["project"]).parent
    assert (run / "original-source.mp4").is_file()
    assert (run / "instructor-voice.wav").is_file()


def test_unknown_lesson_and_unconfirmed_reviews_fail(workspace):
    with pytest.raises(ValueError, match="Unknown lesson"):
        course.build(workspace, lesson_id="unknown", prepare_only=True)
    with pytest.raises(ValueError, match="confirm-reviewed"):
        course.review(workspace, "start", "Test")


def test_review_binds_to_the_film_checked_before_another_build_publishes(workspace, monkeypatch):
    monkeypatch.setattr(course, "lesson_status", lambda *args: {
        "state": "rendered", "fingerprint": "checked-inputs", "movie_sha256": "checked-film"})
    monkeypatch.setattr(course, "state_for", lambda *args: {
        "fingerprint": "newer-inputs", "movie_sha256": "different-film"})
    event = course.review(workspace, "start", "Synthetic fixture declaration", confirmed=True)
    assert event["fingerprint"] == "checked-inputs" and event["movie_sha256"] == "checked-film"


def test_ai_voice_uses_existing_chunker_and_one_explicit_key(workspace, source, tmp_path, monkeypatch):
    course.owners()
    import videokit
    narration = videokit.load("editlane.course_narration")
    audio = tmp_path / "synthetic speech.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-map", "0:a:0", str(audio)],
                   check=True, capture_output=True, timeout=30)
    calls = []

    def resolve(language, *, provider, model):
        assert os.environ["ELEVENLABS_API_KEY"] == "explicit-fixture-key"
        assert os.environ["ELEVENLABS_API_KEYS"] == ""
        assert provider == "elevenlabs" and model == "eleven_v3"

        def speak(chunk, *, lang, voice):
            assert len(chunk) <= 1500 and lang == language and voice == "fixture-voice"
            calls.append(chunk)
            return audio.read_bytes()
        return speak

    monkeypatch.setattr(narration.tts_registry, "resolve_tts", resolve)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "explicit-fixture-key")
    monkeypatch.setenv("ELEVENLABS_API_KEYS", "unrelated-fixture-pool")
    (workspace / "lessons/start/script.txt").write_text("A sentence to teach. " * 170)
    result = course.narrate(workspace, "fixture-voice", lesson_id="start")
    assert result["ok"] and len(calls) >= 3
    read = Path(result["lessons"][0]["audio"])
    receipt = json.loads((read.parent / "NARRATION.json").read_text())
    assert receipt["chunks"] == len(calls)
    assert "explicit-fixture-key" not in json.dumps(receipt)
    assert os.environ["ELEVENLABS_API_KEYS"] == "unrelated-fixture-pool"
    assert course.narrate(workspace, "fixture-voice", lesson_id="start")["lessons"][0]["state"] == "voiceover_kept"
    (workspace / "lessons/start/script.txt").write_text("A revised explanation.")
    assert any("narration no longer matches" in problem for problem in course.status(workspace)["lessons"][0]["problems"])
    regenerated = course.narrate(workspace, "fixture-voice", lesson_id="start")
    assert regenerated["lessons"][0]["state"] == "narrated"
    assert Path(regenerated["lessons"][0]["audio"]) != read and read.is_file()


def test_ai_provider_errors_never_expose_credentials(workspace, monkeypatch):
    course.owners()
    import videokit
    narration = videokit.load("editlane.course_narration")

    def fail(*args, **kwargs):
        raise RuntimeError("private fixture token in provider response")

    monkeypatch.setattr(narration.tts_registry, "resolve_tts", fail)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "private-fixture-key")
    result = course.narrate(workspace, "fixture-voice", lesson_id="start")
    assert not result["ok"]
    assert "private fixture token" not in json.dumps(result)
    assert "voiceover" not in course.load(workspace)["lessons"][0]


def test_public_voice_export_has_no_host_secret_pool():
    contents = (VIDEO / "edit-lane/tts_registry.py").read_text()
    assert ".agent/secrets" not in contents and "_secrets_pool" not in contents


def test_changing_a_source_during_preparation_cannot_be_blessed(workspace, monkeypatch):
    polish, _ = course.owners()
    original = polish.create

    def change_script(*args, **kwargs):
        result = original(*args, **kwargs)
        (workspace / "lessons/start/script.txt").write_text("Edited while the preparation ran")
        return result

    monkeypatch.setattr(polish, "create", change_script)
    result = course.build(workspace, lesson_id="start", prepare_only=True)
    assert not result["ok"]
    assert "inputs changed" in result["lessons"][0]["error"]
    assert course.state_for(workspace, {"id": "start"}) is None


def test_failed_result_assertions_never_publish_a_capture(workspace, tmp_path, source, monkeypatch):
    outline = course.load(workspace)
    lesson = outline["lessons"][0]
    del lesson["source"]
    script = tmp_path / "capture.json"
    dump(script, {"steps": [{"do": "assert", "selector": "#result", "text": "Expected"}]})
    lesson["capture"] = str(script)
    course.write(workspace / "course.json", outline)

    def failed_capture(args, log, **kwargs):
        take = Path(args[args.index("--out-dir") + 1]) / "take"
        take.mkdir(parents=True)
        (take / "screen.mp4").write_bytes(source.read_bytes())
        dump(take / "session.json", {"streams": {"screen": {"path": "screen.mp4"}},
                                   "assertions": [{"status": "failed"}]})

    monkeypatch.setattr(course, "command", failed_capture)
    result = course.build(workspace, lesson_id="start", prepare_only=True)
    assert not result["ok"] and "visible-result checks" in result["lessons"][0]["error"]
    assert not (workspace / "lessons/start/capture-state.json").exists()


def test_capture_receipts_resume_and_allow_explicit_fresh_takes(workspace, tmp_path, source, monkeypatch):
    outline = course.load(workspace)
    lesson = outline["lessons"][0]
    del lesson["source"]
    script = tmp_path / "capture.json"
    dump(script, {"steps": [{"do": "assert", "selector": "#result", "text": "Expected"}]})
    lesson["capture"] = str(script)
    course.write(workspace / "course.json", outline)
    calls = []

    def capture_fixture(args, log, **kwargs):
        # Inject the recorder receipt; encoding and downstream edits use real media.
        take = Path(args[args.index("--out-dir") + 1]) / "take"
        take.mkdir(parents=True)
        (take / "screen.mp4").write_bytes(source.read_bytes())
        evidence = take / "result.png"
        evidence.write_bytes(b"injected result-evidence fixture")
        dump(take / "session.json", {"streams": {"screen": {"path": "screen.mp4"}},
             "assertions": [{"status": "passed", "screenshot": evidence.name, "sha256": course.sha256(evidence)}]})
        calls.append(take)

    monkeypatch.setattr(course, "command", capture_fixture)
    assert course.build(workspace, lesson_id="start", prepare_only=True)["ok"]
    assert len(calls) == 1
    (workspace / "lessons/start/script.txt").write_text("An editorial change can reuse this take")
    assert course.build(workspace, lesson_id="start", prepare_only=True)["ok"]
    assert len(calls) == 1
    assert course.build(workspace, lesson_id="start", prepare_only=True, recapture=True)["ok"]
    assert len(calls) == 2 and (calls[0] / "screen.mp4").is_file()


def test_edits_made_during_a_render_are_not_marked_current(workspace, monkeypatch):
    def changed_render(args, log, **kwargs):
        project = Path(args[args.index("render") + 1])
        movie = Path(args[args.index("--output") + 1])
        movie.write_bytes((project / "assets/screen.mp4").read_bytes())
        html = project / "index.html"
        html.write_text(html.read_text() + "\n<!-- edit after renderer read the project -->")

    monkeypatch.setattr(course, "command", changed_render)
    result = course.build(workspace, lesson_id="start")
    assert not result["ok"] and "changed during rendering" in result["lessons"][0]["error"]
    assert course.state_for(workspace, {"id": "start"}) is None
    assert (Path(result["lessons"][0]["build"]) / "project/index.html").is_file()


@pytest.mark.skipif(os.environ.get("TASKFILM_COURSE_RENDER_TEST") != "1", reason="opt-in real HyperFrames course encode")
def test_real_course_films_resume_rebuild_and_package(workspace, tmp_path):
    # Inputs and voice are synthetic fixtures; these are real checked HF renders.
    def public_build(*, prepare_only=False):
        args = [sys.executable, "-I", "-m", "taskfilm", "course", "build", str(workspace), "--quality", "draft"]
        if prepare_only:
            args.append("--prepare-only")
        result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    resource = tmp_path / "practice.txt"
    resource.write_text("A supplied practice file")
    outline = course.load(workspace)
    outline["lessons"][0]["resources"] = [{"title": "Practice input", "path": str(resource)}]
    course.write(workspace / "course.json", outline)
    # CI has one admitted CPU. Preserve the editable project and select one HF worker.
    prepared = public_build(prepare_only=True)
    for lesson in prepared["lessons"]:
        package_file = Path(lesson["project"]) / "package.json"
        scripts = json.loads(package_file.read_text())
        scripts["scripts"]["render"] += " --workers 1 --no-browser-gpu"
        dump(package_file, scripts)
    first = public_build()
    assert first["ok"], first
    assert first["execution"] == "rendered"
    old = course.state_for(workspace, {"id": "start"})
    old_movie = workspace / old["movie"]
    old_bytes = old_movie.read_bytes()
    assert all(row["reused"] for row in public_build()["lessons"])
    project = workspace / old["project"]
    html = project / "index.html"
    shortened = html.read_text().replace('data-duration="2.0"', 'data-duration="1.0"')
    shortened = shortened.replace('data-duration="2.000"', 'data-duration="1.000"')
    html.write_text(shortened + "\n<!-- instructor refinement -->\n")
    assert course.status(workspace)["lessons"][0]["state"] == "edited"
    changed = public_build()
    assert changed["ok"], changed
    assert not changed["lessons"][0]["reused"] and changed["lessons"][1]["reused"]
    current = course.state_for(workspace, {"id": "start"})
    assert "instructor refinement" in (workspace / current["project"] / "index.html").read_text()
    assert abs(current["qa"]["duration_s"] - 1) < .2
    assert current["qa"]["timing_source"] == "edited_project"
    assert old_movie.read_bytes() == old_bytes
    course.review(workspace, "start", "Synthetic integration declaration", confirmed=True)
    packaged = course.package(workspace, tmp_path / "finished course.zip")
    assert packaged["instructor_review"] == "pending"
    with zipfile.ZipFile(packaged["package"]) as archive:
        manifest = json.loads(archive.read("COURSE.json"))
        assert [row["review"] for row in manifest["lessons"]] == ["reviewed", "not_reviewed"]
        for row in manifest["lessons"]:
            assert hashlib.sha256(archive.read(row["movie"])).hexdigest() == row["movie_sha256"]
            assert "Check your result" in archive.read(row["movie"].replace("lesson.mp4", "learner-guide.txt")).decode()
        assert archive.read(manifest["lessons"][0]["resources"][0]["file"]) == resource.read_bytes()
        assert not any("original" in name or "capture-state" in name or name.endswith(".log") for name in archive.namelist())
    with pytest.raises(ValueError, match="new file"):
        course.package(workspace, Path(packaged["package"]))
    (workspace / "lessons/start/script.txt").write_text("A new explanation")
    assert course.status(workspace)["lessons"][0]["review"] == "not_reviewed"
    with pytest.raises(ValueError, match="before packaging"):
        course.package(workspace, tmp_path / "stale.zip")
