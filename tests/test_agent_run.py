"""Orchestration checks; the opt-in browser test exercises the real recorder."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from taskfilm import pipeline


def script_at(root):
    script = root / "capture.json"
    script.write_text(json.dumps({"name": "A checked feature", "url": "http://127.0.0.1:8765",
        "viewport": {"width": 1280, "height": 720}, "steps": [
            {"do": "beat", "id": "result", "explain": "See the completed task"},
            {"do": "assert", "selector": "#result", "text": "Complete", "screenshot": "result.png"},
            {"do": "wait", "s": 3}]}))
    return script


def retain_take(root, script):
    take = root / "recorder-exact-take"
    take.mkdir(parents=True)
    (take / "screen.mp4").write_bytes(b"explicit unit fixture, not real footage")
    (take / "result.png").write_bytes(b"explicit retained screenshot fixture")
    content = json.loads(script.read_text())
    manifest = {"steps": {"total": len(content["steps"]), "ok": len(content["steps"])},
        "source": {"script_sha256": pipeline.digest(script)},
        "streams": {"screen": {"status": "ok"}}, "assertions": [{
            "selector": "#result", "expected_text": "Complete", "screenshot": "result.png",
            "status": "passed", "sha256": pipeline.digest(take / "result.png"), "dt": 1}]}
    pipeline.write_json(take / "session.json", manifest)
    return take


@pytest.fixture
def owners(monkeypatch):
    calls, behavior = [], {}
    find_tool = pipeline.shutil.which
    # Media owners are fixtures here; unit tests need no host FFmpeg install.
    monkeypatch.setattr(pipeline.shutil, "which", lambda name:
        f"/unit-fixture/{name}" if name in {"ffmpeg", "ffprobe"} else find_tool(name))

    def owner(self, name, *args):
        calls.append(name)
        if name == "capture":
            take = retain_take(Path(args[args.index("--out-dir") + 1]), self.script_path)
            if behavior.get("bad_assertion"):
                record = json.loads((take / "session.json").read_text())
                record["assertions"][0]["status"] = "failed"
                pipeline.write_json(take / "session.json", record)
            if behavior.get("change_source"):
                self.sources[0].write_text("changed while capturing")
        elif name == "edit":
            pipeline.write_json(Path(args[1]) / "plan.json", {"duration_s": 4,
                "beats": [{"start": 0, "end": 4, "explain": "See the completed task"}]})
        elif name == "compose":
            project = Path(args[args.index("--out") + 1])
            project.mkdir(parents=True)
            (project / "index.html").write_text("<html>explicit editable fixture</html>")
        elif name == "render":
            if behavior.pop("fail_render", False):
                raise ValueError("explicit render failure")
            Path(args[args.index("--output") + 1]).write_bytes(b"explicit movie fixture")

    def verify(self):
        calls.append("verify")
        root = self.root / "reviews" / uuid4().hex[:8]
        root.mkdir(parents=True)
        frame, sheet = root / "frame.png", root / "contact.jpg"
        frame.write_bytes(b"explicit review frame fixture")
        sheet.write_bytes(b"explicit contact sheet fixture")
        self.state.update(video_verified=True, duration_s=4, audio_review="not_applicable")
        self.state["artifacts"].update(poster=str(frame), contact_sheet=str(sheet), frames=[str(frame)],
                                        preview=str(self.root / "preview.html"))
        return [frame, sheet]

    monkeypatch.setattr(pipeline.Pipeline, "owner", owner)
    monkeypatch.setattr(pipeline.Pipeline, "verify_video", verify)
    return calls, behavior


def run(root, capsys, *extra):
    code = pipeline.main([str(root / "capture.json"), "--out", str(root / "film"),
                          "--render-mode", "hyperframes", "--json", *extra])
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    return code, json.loads(output)


def test_compact_handoff_and_identical_resume(tmp_path, capsys, owners):
    script_at(tmp_path)
    code, result = run(tmp_path, capsys)
    assert code == 0 and result["status"] == "rendered", result
    assert result["capture_verified"] and result["video_verified"]
    assert result["visual_review"] == "not_performed"
    assert result["audio_review"] == "not_applicable"
    assert len(json.dumps(result)) < 3500
    for name in ("movie", "preview", "poster", "result_image", "contact_sheet"):
        assert Path(result["artifacts"][name]).is_file()
    calls = owners[0].copy()
    code, resumed = run(tmp_path, capsys, "--resume")
    assert code == 0
    assert owners[0] == calls
    assert resumed["reused"] == ["validate", "capture", "edit", "compose", "render", "verify"]
    assert resumed["artifacts"] == result["artifacts"]


def test_failed_render_resumes_without_repeating_the_product_task(tmp_path, capsys, owners):
    script_at(tmp_path)
    owners[1]["fail_render"] = True
    code, failed = run(tmp_path, capsys)
    assert code == 2 and failed["status"] == "blocked"
    assert failed["capture_verified"] and not failed["video_verified"]
    assert "movie" not in failed["artifacts"]
    assert "verify" not in owners[0]
    code, ready = run(tmp_path, capsys, "--resume")
    assert code == 0
    assert owners[0].count("capture") == 1
    assert owners[0].count("compose") == 1
    assert owners[0].count("render") == 2
    assert ready["reused"] == ["validate", "capture", "edit", "compose"]


def test_quality_change_only_renders_and_reviews(tmp_path, capsys, owners):
    script_at(tmp_path)
    _, first = run(tmp_path, capsys)
    code, second = run(tmp_path, capsys, "--resume", "--quality", "looks")
    assert code == 0
    assert owners[0].count("capture") == 1 and owners[0].count("compose") == 1
    assert owners[0].count("render") == 2 and owners[0].count("verify") == 2
    assert first["artifacts"]["movie"] != second["artifacts"]["movie"]
    assert Path(first["artifacts"]["movie"]).is_file()


@pytest.mark.parametrize("failure", ["bad_assertion", "missing_assertion"])
def test_failed_or_missing_assertion_never_renders(tmp_path, capsys, owners, failure):
    script = script_at(tmp_path)
    if failure == "bad_assertion":
        owners[1][failure] = True
    else:
        content = json.loads(script.read_text())
        content["steps"] = [step for step in content["steps"] if step["do"] != "assert"]
        script.write_text(json.dumps(content))
    code, result = run(tmp_path, capsys)
    assert code == 2 and result["status"] == "blocked"
    assert "render" not in owners[0]
    assert not result["capture_verified"]


@pytest.mark.parametrize("modified", ["result_image", "movie"])
def test_tampered_output_is_not_reused_or_automatically_recaptured(tmp_path, capsys, owners, modified):
    script_at(tmp_path)
    _, first = run(tmp_path, capsys)
    Path(first["artifacts"][modified]).write_bytes(b"tampered")
    code, result = run(tmp_path, capsys, "--resume")
    assert code == 2 and "output changed" in result["error"]
    assert not result["video_verified"]
    if modified == "result_image":
        assert not result["capture_verified"]
    assert owners[0].count("capture") == 1


def test_changed_tracked_source_refuses_resume(tmp_path, capsys, owners):
    script_at(tmp_path)
    source = tmp_path / "backend.py"
    source.write_text("checked backend version")
    run(tmp_path, capsys, "--source", str(source))
    calls = owners[0].copy()
    source.write_text("another backend version")
    code, result = run(tmp_path, capsys, "--resume", "--source", str(source))
    assert code == 2 and result["status"] == "stale"
    assert not result["capture_verified"] and not result["video_verified"]
    assert owners[0] == calls


def test_source_change_during_capture_stops_before_composition(tmp_path, capsys, owners):
    script_at(tmp_path)
    source = tmp_path / "ui.tsx"
    source.write_text("checked UI version")
    owners[1]["change_source"] = True
    code, result = run(tmp_path, capsys, "--source", str(source))
    assert code == 2 and result["status"] == "stale"
    assert "capture" in owners[0] and "edit" not in owners[0]
    assert not result["capture_verified"]


def test_receipts_must_match_script_assertion(tmp_path):
    script = script_at(tmp_path)
    take = retain_take(tmp_path / "takes", script)
    content = json.loads(script.read_text())
    content["steps"][1]["text"] = "Different result"
    with pytest.raises(ValueError, match="does not match"):
        pipeline.verify_take(take, content, pipeline.digest(script))


def test_stage_deadline_reaps_its_process(tmp_path):
    from types import SimpleNamespace
    script = script_at(tmp_path)
    worker = pipeline.Pipeline(SimpleNamespace(out=tmp_path / "film", script=script, source=[], timeout=.1))
    worker.root.mkdir()
    with pytest.raises(subprocess.TimeoutExpired):
        worker.command("deadline", [sys.executable, "-c", "import time; time.sleep(30)"])
    assert worker.state["log"]


def test_existing_take_skips_browser_and_keeps_original_plan(tmp_path, capsys, owners, monkeypatch):
    script = script_at(tmp_path)
    original = retain_take(tmp_path / "already-checked", script)
    (original / "plan.json").write_text("original edit stays unchanged")
    # Use the real import branch, with the other expensive owners stubbed.
    monkeypatch.setattr(pipeline.Pipeline, "capture", REAL_CAPTURE)
    code, result = run(tmp_path, capsys, "--take", str(original))
    assert code == 0
    assert "browser-check" not in owners[0] and "capture" not in owners[0]
    assert result["artifacts"]["source_take"] == str(original)
    assert Path(result["artifacts"]["take"]) != original
    assert (original / "plan.json").read_text() == "original edit stays unchanged"


REAL_CAPTURE = pipeline.Pipeline.capture


def test_default_handoff_copies_pixels_without_a_second_browser_render(tmp_path, capsys, owners, monkeypatch):
    script_at(tmp_path)
    commands = []
    def prepare(self, name, args, cwd=None):
        commands.append(args)
        Path(args[-1]).write_bytes(Path(args[args.index("-i") + 1]).read_bytes())
    monkeypatch.setattr(pipeline.Pipeline, "command", prepare)
    code, result = run(tmp_path, capsys, "--render-mode", "capture")
    assert code == 0 and result["render_mode"] == "capture"
    assert "render" not in owners[0]
    assert commands[0][commands[0].index("-c") + 1] == "copy"
    take = Path(result["artifacts"]["take"])
    assert Path(result["artifacts"]["movie"]).read_bytes() == (take / "screen.mp4").read_bytes()
    assert Path(result["artifacts"]["captions"]).read_text().startswith("WEBVTT")
    code, motion = run(tmp_path, capsys, "--resume", "--render-mode", "hyperframes")
    assert code == 0 and motion["reused"] == ["validate", "capture", "edit", "compose"]
    assert owners[0].count("capture") == 1


def test_preview_escapes_product_copy(tmp_path, capsys, owners):
    script = script_at(tmp_path)
    content = json.loads(script.read_text())
    content["name"] = '<script>alert("product")</script>'
    script.write_text(json.dumps(content))
    code, result = run(tmp_path, capsys)
    assert code == 0
    preview = Path(result["artifacts"]["preview"]).read_text()
    assert '<script>alert("product")</script>' not in preview
    assert "&lt;script&gt;" in preview


def test_existing_run_lock_is_not_removed(tmp_path, owners):
    script_at(tmp_path)
    root = tmp_path / "film"
    root.mkdir()
    (root / ".run.lock").write_text("another run")
    with pytest.raises(ValueError, match="owns"):
        pipeline.main([str(tmp_path / "capture.json"), "--out", str(root), "--resume"])
    assert (root / ".run.lock").read_text() == "another run"


def test_feature_skill_installs_with_its_references(tmp_path):
    from taskfilm.cli import main
    destination = tmp_path / "skill"
    assert main(["skill", str(destination), "--name", "taskfilm-feature-explainer"]) == 0
    assert (destination / "SKILL.md").is_file()
    assert (destination / "references/workflow.md").is_file()
    assert (destination / "references/in-chat.md").is_file()
