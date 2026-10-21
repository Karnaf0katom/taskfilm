"""Exercise the directed promo recipe without invoking browsers or renderers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest


def _promo_harness(tmp_path, monkeypatch, *, bad_evidence=False, fail_stage=None):
    from taskfilm import cli
    from taskfilm import demo

    owners = tmp_path / "owners"
    for owner in cli.OWNERS.values():
        path = owners / owner
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# owner\n")
    monkeypatch.setattr(cli, "VIDEO", owners)
    monkeypatch.setattr(cli, "node_version", lambda: "v22.1.0")
    monkeypatch.setattr(demo.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(demo.shutil, "which", lambda name: f"/tools/{name}")

    state = {"commands": [], "prepare": None, "capture_url": None}

    def initialize(sample: Path):
        (sample / "taskboard").mkdir(parents=True)
        (sample / "taskboard/index.html").write_text("<html>sample</html>")
        (sample / "brand").mkdir()
        for name in ("request.json", "promo.json", "feature.json", "motion-spec.json"):
            (sample / name).write_text("{}\n")
        capture = {"url": "unused", "viewport": {"width": 3840, "height": 2160},
                   "steps": [{"do": "assert", "screenshot": f"proof-{i}.png"} for i in range(4)]}
        (sample / "motion-capture.json").write_text(json.dumps(capture))
        (sample / "prepare-motion.py").write_text("# exported helper\n")
        return 0

    def run_owner(command, args, *, log=None):
        state["commands"].append((command, list(args)))
        stage = f"motion-{args[args.index('--format') + 1]}" if command == "motion" else command
        if fail_stage == stage:
            log.write(f"injected {stage} failure\n")
            return 7
        if command == "capture" and args[0] == "rec":
            state["capture_url"] = json.loads(Path(args[1]).read_text())["url"]
            take = Path(args[args.index("--out-dir") + 1]) / "exacttake"
            take.mkdir(parents=True)
            assertions = []
            for i in range(4):
                screenshot = take / f"proof-{i}.png"
                screenshot.write_bytes(f"proof {i}".encode())
                digest = "wrong" if bad_evidence and i == 2 else hashlib.sha256(screenshot.read_bytes()).hexdigest()
                assertions.append({"status": "passed", "screenshot": screenshot.name, "sha256": digest})
            session = {"steps": {"total": 12, "ok": 12}, "assertions": assertions,
                       "streams": {"screen": {"status": "ok"}}}
            (take / "session.json").write_text(json.dumps(session))
        if command == "motion":
            film = Path(args[0])
            fmt = args[args.index("--format") + 1]
            out = film / "cuts" / fmt
            out.mkdir(parents=True)
            for name in ("index.html", "hyperframes.json", "EDIT-DECISIONS.json"):
                (out / name).write_text("{}\n")
        return 0

    def prepare(args, *, stdout, stderr):
        state["prepare"] = list(args)
        (Path(args[args.index("--sample") + 1]) / "spec.json").write_text("{}\n")
        stdout.write('{"prepared": true}\n')
        return SimpleNamespace(returncode=5 if fail_stage == "prepare-motion" else 0)

    def render_project(project, output, quality, *, log=None):
        state.setdefault("renders", []).append((project, output, quality))
        output.write_bytes(f"rendered {project.name}".encode())
        if fail_stage == f"render-{project.name}":
            log.write(f"injected render-{project.name} failure\n")
            return 8
        return 0

    monkeypatch.setattr(cli, "initialize", initialize)
    monkeypatch.setattr(cli, "run_owner", run_owner)
    monkeypatch.setattr(cli, "render_project", render_project)
    monkeypatch.setattr(demo.subprocess, "run", prepare)
    return state


def _assert_server_stopped(url: str):
    address = urlparse(url)
    with socket.socket() as client:
        client.settimeout(2)
        assert client.connect_ex((address.hostname, address.port)) != 0


def test_promo_rejects_missing_preflight_before_creating_destination(tmp_path, monkeypatch):
    from taskfilm import demo

    monkeypatch.setattr(demo.importlib.util, "find_spec", lambda _name: None)
    destination = tmp_path / "promo"
    with pytest.raises(ValueError, match="prerequisites.*numpy"):
        demo.demonstrate(destination, mode="promo")
    assert not destination.exists()


def test_promo_prepare_failure_keeps_log_and_stops_server(tmp_path, monkeypatch):
    from taskfilm.demo import demonstrate

    state = _promo_harness(tmp_path, monkeypatch, fail_stage="prepare-motion")
    destination = tmp_path / "failed-promo"
    with pytest.raises(ValueError, match="prepare-motion failed .*exit 5"):
        demonstrate(destination, mode="promo")
    assert "prepared" in (destination / "logs/prepare-motion.log").read_text()
    assert not (destination / "DEMO-RESULT.json").exists()
    _assert_server_stopped(state["capture_url"])


def test_promo_prepares_both_formats_without_node_or_npm(tmp_path, monkeypatch):
    from taskfilm import cli, demo

    state = _promo_harness(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "node_version", lambda: None)
    monkeypatch.setattr(demo.shutil, "which",
                        lambda name: None if name in {"node", "npm"} else f"/tools/{name}")
    report = demo.demonstrate(tmp_path / "editable-promo", mode="promo", format="both")
    assert report["rendered"] is False and report["movie"] is None
    assert len(report["deliverables"]) == 2
    assert all(item["movie"] is None and Path(item["edit_decisions"]).is_file()
               for item in report["deliverables"])
    assert "renders" not in state
    _assert_server_stopped(state["capture_url"])


def test_promo_rejects_bad_screenshot_evidence(tmp_path, monkeypatch):
    from taskfilm.demo import demonstrate

    state = _promo_harness(tmp_path, monkeypatch, bad_evidence=True)
    destination = tmp_path / "bad-evidence"
    with pytest.raises(ValueError, match="evidence failed verification"):
        demonstrate(destination, mode="promo")
    assert state["prepare"] is None
    assert not (destination / "DEMO-RESULT.json").exists()
    _assert_server_stopped(state["capture_url"])


def test_promo_both_formats_use_one_exact_take_and_report_outputs(tmp_path, monkeypatch):
    from taskfilm.demo import demonstrate

    state = _promo_harness(tmp_path, monkeypatch)
    destination = tmp_path / "both-formats"
    report = demonstrate(destination, mode="promo", format="both", render=True)

    assert report["schema"] == "taskfilm-demo/v1"
    assert report["mode"] == "promo" and report["formats"] == ["landscape", "portrait"]
    assert report["assertions_verified"] == 4 and report["final_video_review"] == "not_performed"
    take = Path(report["take"])
    assert len(report["assertions"]) == 4
    assert all(proof["status"] == "passed" and
               hashlib.sha256((take / proof["screenshot"]).read_bytes()).hexdigest() == proof["sha256"]
               for proof in report["assertions"])
    assert report["session_sha256"] == hashlib.sha256(Path(report["session"]).read_bytes()).hexdigest()
    assert [item["format"] for item in report["deliverables"]] == ["landscape", "portrait"]
    assert report["composition"] == report["deliverables"][0]["composition"]
    assert report["rendered"] is True
    assert [Path(item["movie"]).name for item in report["deliverables"]] == [
        "promo-landscape.mp4", "promo-portrait.mp4"]
    assert all(item["rendered"] and item["movie_sha256"] for item in report["deliverables"])
    assert report["movie"] == report["deliverables"][0]["movie"]
    motion = [args for command, args in state["commands"] if command == "motion"]
    assert len(motion) == 2
    assert motion[0][-1] == motion[1][-1] == str(destination / "takes/exacttake")
    assert state["prepare"][0] and state["prepare"][1].endswith("sample/prepare-motion.py")
    assert state["prepare"][-2:] == ["--url", state["capture_url"]]
    assert json.loads((destination / "DEMO-RESULT.json").read_text()) == report
    _assert_server_stopped(state["capture_url"])


def test_promo_second_format_failure_writes_no_success_receipt(tmp_path, monkeypatch):
    from taskfilm.demo import demonstrate

    _promo_harness(tmp_path, monkeypatch, fail_stage="motion-portrait")
    destination = tmp_path / "author-failure"
    with pytest.raises(ValueError, match="motion-portrait failed .*exit 7"):
        demonstrate(destination, mode="promo", format="both")
    assert "injected motion-portrait" in (destination / "logs/motion-portrait.log").read_text()
    assert not (destination / "DEMO-RESULT.json").exists()


def test_promo_second_render_failure_keeps_first_movie_without_success_receipt(tmp_path, monkeypatch):
    from taskfilm.demo import demonstrate

    state = _promo_harness(tmp_path, monkeypatch, fail_stage="render-portrait")
    destination = tmp_path / "render-failure"
    with pytest.raises(ValueError, match="render-portrait failed"):
        demonstrate(destination, mode="promo", format="both", render=True)
    assert (destination / "promo-landscape.mp4").stat().st_size > 0
    assert "injected render-portrait" in (destination / "logs/render-portrait.log").read_text()
    assert not (destination / "DEMO-RESULT.json").exists()
    _assert_server_stopped(state["capture_url"])
