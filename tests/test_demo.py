"""Check the installed first-run recipe and its temporary-server lifecycle."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlparse

import pytest


def test_demo_help_explains_first_run_without_starting_it(tmp_path):
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "demo", "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert "--render" in result.stdout and "new directory" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_demo_preserves_an_existing_directory(tmp_path):
    existing = tmp_path / "my demo"
    existing.mkdir()
    source = existing / "keep.txt"
    source.write_text("my existing project\n")
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "demo", str(existing)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "new directory" in result.stderr
    assert source.read_text() == "my existing project\n"
    assert list(existing.iterdir()) == [source]


def test_init_keeps_editable_source_and_excludes_install_bytecode(tmp_path):
    import taskfilm

    destination = tmp_path / "portable sample"
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "init", str(destination)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = Path(taskfilm.__file__).parent / "examples/prepare-oss-review.py"
    assert (destination / "prepare-oss-review.py").read_bytes() == installed.read_bytes()
    assert not list(destination.rglob("__pycache__"))
    assert not list(destination.rglob("*.pyc"))


def test_failed_capture_stops_server_and_keeps_diagnostic_log(tmp_path, monkeypatch):
    from taskfilm import cli
    from taskfilm.demo import demonstrate

    def reject_capture(command, args, *, log=None):
        if command == "capture" and args[0] == "rec":
            log.write("Browser capture failed before producing a take.\n")
            return 9
        return 0

    monkeypatch.setattr(cli, "run_owner", reject_capture)
    destination = tmp_path / "failed film"
    with pytest.raises(ValueError, match="capture failed .*exit 9"):
        demonstrate(destination)
    assert "Browser capture failed" in (destination / "logs/capture.log").read_text()
    assert not (destination / "DEMO-RESULT.json").exists()
    address = urlparse(json.loads((destination / "capture.json").read_text())["url"])
    with socket.socket() as client:
        client.settimeout(2)
        assert client.connect_ex((address.hostname, address.port)) != 0


def test_render_requires_supported_node_before_starting_demo(tmp_path, monkeypatch):
    from taskfilm import cli
    from taskfilm.demo import demonstrate

    monkeypatch.setattr(cli, "node_version", lambda: "v18.20.8")
    destination = tmp_path / "unsupported node"
    with pytest.raises(ValueError, match="Node.js 22"):
        demonstrate(destination, render=True)
    assert not destination.exists()


def test_render_refuses_a_dangling_output_symlink(tmp_path, monkeypatch):
    from taskfilm import cli

    project = tmp_path / "composition"
    project.mkdir()
    (project / "hyperframes.json").write_text("{}")
    output = tmp_path / "lesson.mp4"
    target = tmp_path / "keep-this-target-missing.mp4"
    output.symlink_to(target)
    monkeypatch.setattr(cli, "node_version", lambda: "v22.0.0")
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/test/tool")
    with pytest.raises(ValueError, match="new file"):
        cli.render_project(project, output, "draft")
    assert output.is_symlink() and not target.exists()


@pytest.mark.skipif(os.environ.get("TASKFILM_BROWSER_TEST") != "1", reason="opt-in real browser capture")
def test_installed_demo_retains_a_real_result_and_stops_server(tmp_path):
    destination = tmp_path / "first film with spaces"
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "demo", str(destination)],
                            cwd=tmp_path, capture_output=True, text=True,
                            timeout=int(os.environ.get("TASKFILM_CAPTURE_TEST_TIMEOUT", "300")))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report == json.loads((destination / "DEMO-RESULT.json").read_text())
    assert report["rendered"] is False and report["movie"] is None
    assert report["assertions_verified"] == 3
    assert report["steps"]["ok"] == report["steps"]["total"]
    take = Path(report["take"])
    session = json.loads((take / "session.json").read_text())
    assert (take / "screen.mp4").stat().st_size > 1000
    for assertion in session["assertions"]:
        assert assertion["status"] == "passed"
        assert hashlib.sha256((take / assertion["screenshot"]).read_bytes()).hexdigest() == assertion["sha256"]
    assert (take / "plan.json").is_file()
    assert (destination / "story-plan/product-story-plan.json").is_file()
    assert (destination / "composition/index.html").stat().st_size > 100
    package = json.loads((destination / "composition/package.json").read_text())
    assert "hyperframes@0.8.134" in package["scripts"]["render"]
    assert report["final_video_review"] == "not_performed"
    assert not list((destination / "sample").rglob("__pycache__"))
    address = urlparse(json.loads((destination / "capture.json").read_text())["url"])
    with socket.socket() as client:
        client.settimeout(2)
        assert client.connect_ex((address.hostname, address.port)) != 0
