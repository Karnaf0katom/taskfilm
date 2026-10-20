"""Capture contract and failure checks, plus an opt-in real OpenGCUA workflow."""
from __future__ import annotations

import asyncio
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace

from PIL import Image
import pytest


def owner_path():
    local = Path(__file__).parents[1]
    if (local / "opengcua_capture.py").is_file():
        return local
    try:
        import taskfilm
        installed = Path(taskfilm.__file__).parent / "_vendor/video/capture-lane"
        if (installed / "opengcua_capture.py").is_file():
            return installed
    except ImportError:
        pass
    return local


sys.path.insert(0, str(owner_path()))
import opengcua_capture as gcua


@pytest.fixture
def options(tmp_path):
    program = tmp_path / "workflow.py"
    program.write_text("async def run(tab, film):\n    pass\n")
    return dict(program=program, url="http://127.0.0.1:8765/", out=tmp_path / "take",
                width=1280, height=720, fps=8, timeout=120)


@pytest.mark.parametrize("field,value", [
    # Assemble explicitly synthetic userinfo: the public source scanner also
    # rejects literal credential-bearing URLs in fixtures.
    ("url", "file:///etc/passwd"), ("url", "https://" + "fixture:fixture" + "@example.test"),
    ("width", 1281), ("height", 99999), ("fps", float("nan")),
    ("fps", 0), ("fps", 30), ("timeout", True), ("timeout", float("inf")),
])
def test_invalid_request_leaves_no_take(options, field, value):
    options[field] = value
    with pytest.raises(ValueError):
        gcua.validate_options(**options)
    assert not options["out"].exists()


def test_existing_take_and_dangling_output_symlink_are_never_overwritten(options):
    out = options["out"]
    out.mkdir()
    sentinel = out / "session.json"
    sentinel.write_text("existing take")
    with pytest.raises(ValueError, match="new directory"):
        gcua.validate_options(**options)
    assert sentinel.read_text() == "existing take"
    sentinel.unlink()
    out.rmdir()
    out.symlink_to(out.parent / "missing-target")
    with pytest.raises(ValueError, match="new directory"):
        gcua.validate_options(**options)


def test_program_bytes_are_the_checked_bytes_even_if_source_changes(options):
    data = gcua.validate_options(**options)
    options["program"].write_text("raise RuntimeError('changed after checking')\n")
    run = gcua.load_program(data, options["program"])
    asyncio.run(run(None, None))


def test_program_entry_must_be_async_and_accept_the_capture_handles(options):
    for data in (b"def run(tab, film): pass", b"async def run(): pass", b"x = 1"):
        with pytest.raises((ValueError, TypeError)):
            gcua.load_program(data, options["program"])


def test_optional_sdk_absence_is_actionable_and_does_not_break_normal_capture(monkeypatch):
    monkeypatch.setattr(gcua, "sys", SimpleNamespace(version_info=(3, 11)))
    def missing(_):
        raise gcua.metadata.PackageNotFoundError
    monkeypatch.setattr(gcua.metadata, "version", missing)
    with pytest.raises(ValueError, match="optional OpenGCUA SDK is missing"):
        gcua.runtime_class()
    assert gcua.webrec.validate_script({"url": "http://localhost", "steps": [{"do": "wait"}]}) == []


def test_unknown_sdk_version_is_refused_before_starting_a_browser(monkeypatch):
    monkeypatch.setattr(gcua, "sys", SimpleNamespace(version_info=(3, 11)))
    monkeypatch.setattr(gcua.metadata, "version", lambda _: "99.0.0")
    with pytest.raises(ValueError, match="supports qwen-intelligence-sdk"):
        gcua.runtime_class()


def test_sdk_python_floor_does_not_affect_ordinary_capture(monkeypatch):
    monkeypatch.setattr(gcua, "sys", SimpleNamespace(version_info=(3, 10)))
    with pytest.raises(ValueError, match="requires Python 3.11"):
        gcua.runtime_class()
    assert gcua.webrec.validate_script({"url": "http://localhost", "steps": [{"do": "wait"}]}) == []


def test_command_help_works_without_loading_an_optional_runtime(tmp_path):
    result = subprocess.run([sys.executable, str(owner_path() / "webrec.py"), "gcua", "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--fps" in result.stdout and "async def run(tab, film)" in result.stdout


def test_startup_failure_leaves_a_failed_manifest_and_no_claimed_result(options, monkeypatch):
    class BrokenRuntime:
        async def __aenter__(self):
            raise RuntimeError("example failure; its message is not public evidence")
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(gcua, "runtime_class", lambda: BrokenRuntime)
    args = SimpleNamespace(**options, headed=False, keep_frames=False)
    assert asyncio.run(gcua.record_program(args)) == 1
    session = json.loads((options["out"] / "session.json").read_text())
    assert session["driver"]["status"] == "failed"
    assert session["driver"]["completed"] is False
    assert session["result_verification"] == "not_verified"
    assert session["streams"]["screen"]["path"] is None
    assert session["steps"]["failures"] == [{"stage": "sdk_start", "type": "RuntimeError"}]
    assert "example failure" not in json.dumps(session)


def test_recorder_failure_stops_and_joins_the_program():
    async def scenario():
        stopped = asyncio.Event()
        async def program(tab, film):
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()
        class Recorder:
            async def loop(self):
                await asyncio.sleep(.01)
                raise ValueError("screen stream failed")
        with pytest.raises(ValueError, match="screen stream failed"):
            await gcua.run_recorded_program(program, None, None, Recorder(), 1)
        assert stopped.is_set()
    asyncio.run(scenario())


def test_program_deadline_cancels_and_joins_both_tasks():
    async def scenario():
        stopped = set()
        async def program(tab, film):
            try:
                await asyncio.sleep(60)
            finally:
                stopped.add("program")
        class Recorder:
            async def loop(self):
                try:
                    await asyncio.sleep(60)
                finally:
                    stopped.add("recorder")
        with pytest.raises(TimeoutError):
            await gcua.run_recorded_program(program, None, None, Recorder(), .01)
        assert stopped == {"program", "recorder"}
    asyncio.run(scenario())


def test_failing_assertion_stays_failed_if_program_catches_it(tmp_path):
    class Missing:
        async def count(self, **kwargs):
            return 0
    bundle = gcua.webrec.Bundle(tmp_path / "take")
    film = gcua.Film(None, SimpleNamespace(playwright=SimpleNamespace(locator=lambda _: Missing())),
                     bundle, 1280, 720)
    try:
        with pytest.raises(AssertionError):
            asyncio.run(film.assert_text("#missing", "Result", screenshot="result.png", timeout=.01))
        assert bundle.assertions[0]["status"] == "failed"
        assert not (bundle.dir / "result.png").exists()
    finally:
        bundle.close()


def test_viewport_change_is_not_encoded_as_the_requested_geometry():
    data = io.BytesIO()
    Image.new("RGB", (640, 480)).save(data, format="PNG")
    with pytest.raises(ValueError, match="viewport changed"):
        gcua.screenshot_bytes(data.getvalue(), 1280, 720)


def test_background_capture_never_writes_or_replaces_sdk_observations(tmp_path):
    # Upstream classifies evaluate as a write, screenshot as a read. A camera
    # that polls evaluate or ui.observe would invalidate the program's targets.
    data = io.BytesIO()
    Image.new("RGB", (1280, 720)).save(data, format="JPEG")
    class ReadOnlyTab:
        @property
        def ui(self):
            raise AssertionError("recording must not replace live SDK observations")
        async def evaluate(self, *args):
            raise AssertionError("recording must not evaluate code during a workflow")
        @property
        def playwright(self):
            return self
        async def screenshot(self, **kwargs):
            return data.getvalue()
    bundle = gcua.webrec.Bundle(tmp_path / "take")
    try:
        recorder = gcua.TabRecorder(ReadOnlyTab(), bundle, 1280, 720, 8)
        asyncio.run(recorder.capture())
        assert len(recorder.stream.frames) == 1
        assert bundle.t0 is not None
    finally:
        bundle.close()


@pytest.mark.skipif(os.getenv("TASKFILM_GCUA_TEST") != "1", reason="opt-in real SDK/browser workflow")
def test_real_sdk_drives_the_task_and_existing_planner_reads_its_take(tmp_path):
    # All actions are against our own original local app. No model, remote app,
    # credentials, browser attachment or provider is involved.
    local_owner = (Path(__file__).parents[1] / "opengcua_capture.py").is_file()
    if local_owner:
        examples = Path(__file__).parents[2] / "taskfilm/examples"
    else:
        import taskfilm
        examples = Path(taskfilm.__file__).parent / "examples"
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(examples / "taskboard"), **kwargs)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = tmp_path / "sdk-take"
    url = f"http://127.0.0.1:{server.server_port}/"
    command = ([sys.executable, str(owner_path() / "webrec.py")] if local_owner else
               [sys.executable, "-I", "-m", "taskfilm", "capture"])
    try:
        process = subprocess.run([*command, "gcua",
            str(examples / "opengcua-taskboard.py"), "--url", url, "--out", str(out)],
            cwd=tmp_path, capture_output=True, text=True, timeout=300)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert process.returncode == 0, process.stdout + process.stderr
    manifest = json.loads((out / "session.json").read_text())
    assert manifest["driver"]["completed"] is True
    assert manifest["driver"]["sdk_version"] == gcua.SDK_VERSION
    assert manifest["result_verification"] == "dom_assertions_passed"
    assert manifest["visual_verification"] == "not_performed"
    assert manifest["streams"]["screen"]["capture_mode"] == "sampled"
    assert manifest["streams"]["screen"]["frames"] >= 10
    assert manifest["streams"]["input"]["counts"]["click"] >= 4
    assert len(manifest["assertions"]) == 3
    for assertion in manifest["assertions"]:
        assert assertion["status"] == "passed"
        assert hashlib.sha256((out / assertion["screenshot"]).read_bytes()).hexdigest() == assertion["sha256"]
    keys = [json.loads(line) for line in (out / "input.jsonl").read_text().splitlines()]
    assert all(len(event["key"]) > 1 for event in keys if "key" in event)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
        "-of", "json", str(out / "screen.mp4")], capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == (1280, 720)
    planned = subprocess.run([sys.executable, str(owner_path() / "plan.py"), str(out), "--no-retime"],
                             capture_output=True, text=True, timeout=90)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    plan = json.loads((out / "plan.json").read_text())
    assert len(plan["beats"]) == 3
    assert plan["zooms"]
