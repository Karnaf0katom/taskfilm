"""Exercise the installed CLI from an unrelated cwd, not monorepo imports."""
from __future__ import annotations

import hashlib
from importlib import metadata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest


def invoke(cwd, *args, timeout=60):
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", *map(str, args)],
                            cwd=cwd, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture
def example(tmp_path):
    invoke(tmp_path, "init", tmp_path / "sample")
    return tmp_path / "sample"


def test_installed_planner_from_unrelated_directory(example, tmp_path):
    for story, mode in (("feature.json", "feature_demo"), ("promo.json", "saas_launch")):
        bundle = tmp_path / mode
        invoke(tmp_path, "story", "--request", example / "request.json", "--story", example / story,
               "--out", bundle)
        plan = json.loads((bundle / "product-story-plan.json").read_text())
        assert plan["mode"] == mode
        assert plan["claims"] and plan["capture_requirements"]
        assert len(list(bundle.iterdir())) == 6
        assert "PREPRODUCTION ONLY" in (bundle / "capture-brief.md").read_text()


def test_oss_sample_binds_actual_pinned_document_and_preserves_review_scope(example, tmp_path):
    # Explicit offline repository fixture; no public repository or runtime proof is asserted.
    readme = Path(__file__).parents[1] / "PUBLIC-README.md"
    pack = {"repository_url": "https://github.com/example/taskfilm-test-fixture",
            "resolved_commit": "a" * 40, "license_spdx": "UNKNOWN",
            "documents": [{"path": "README.md", "sha256": hashlib.sha256(readme.read_bytes()).hexdigest()}]}
    pack_path = tmp_path / "repo-pack.json"
    pack_path.write_text(json.dumps(pack))
    request = tmp_path / "oss-request.json"
    prepared = subprocess.run([sys.executable, str(example / "prepare-oss-review.py"),
        "--repo-pack", str(pack_path), "--readme", str(readme), "--out", str(request)],
        cwd=tmp_path, capture_output=True, text=True)
    assert prepared.returncode == 0, prepared.stderr
    bundle = tmp_path / "oss-plan"
    invoke(tmp_path, "story", "--request", request, "--story", example / "oss.json",
           "--repo-pack", pack_path, "--out", bundle)
    plan = json.loads((bundle / "product-story-plan.json").read_text())
    assert plan["mode"] == "github_review"
    assert plan["repository"]["commit"] == pack["resolved_commit"]
    assert plan["repository"]["runtime_review"] == "not_performed"
    assert plan["review"]["runtime_verified"] is False
    assert plan["execution"] == "planned_only" and plan["ready_to_render"] is False
    assert {row["id"] for row in plan["claims"]} >= {"fit", "limitation"}
    wrong_readme = tmp_path / "changed-readme.md"
    wrong_readme.write_text(readme.read_text() + "\nChanged after pinning.\n")
    refused = subprocess.run([sys.executable, str(example / "prepare-oss-review.py"),
        "--repo-pack", str(pack_path), "--readme", str(wrong_readme), "--out", str(tmp_path / "refused.json")],
        cwd=tmp_path, capture_output=True, text=True)
    assert refused.returncode == 2
    assert "do not match" in refused.stderr
    assert not (tmp_path / "refused.json").exists()


@pytest.mark.parametrize("command,expected", [
    ("story", "--request"), ("capture", "discover"), ("edit", "--no-retime"),
    ("compose", "--max-scale"), ("reel", "--no-title"),
    ("repo-pack", "--ref"), ("package", "--help"),
    ("motion", "--format"),
])
def test_every_supported_owner_loads(tmp_path, command, expected):
    result = invoke(tmp_path, command, "--help")
    assert expected in result.stdout


def test_original_capture_script_validates(example, tmp_path):
    invoke(tmp_path, "capture", "validate", example / "capture.json")


def test_init_refuses_to_overwrite(example, tmp_path):
    before = hashlib.sha256((example / "request.json").read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "init", str(example)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert hashlib.sha256((example / "request.json").read_bytes()).hexdigest() == before


def test_custom_brand_uses_supplied_files(example, tmp_path):
    request = json.loads((example / "request.json").read_text())
    request["brand"]["pack"] = "my-product"
    (example / "request.json").write_text(json.dumps(request))
    brand = json.loads((example / "brand/taskfilm-demo.json").read_text())
    brand.update(name="my-product", wordmark="MY PRODUCT")
    brand["palette"]["accent"] = "#A34B30"
    (example / "brand/my-product.json").write_text(json.dumps(brand))
    result = invoke(tmp_path, "story", "--request", example / "request.json", "--story",
                    example / "feature.json", "--brand-dir", example / "brand")
    plan = json.loads(result.stdout)
    assert plan["brand_identity"]["wordmark"] == "MY PRODUCT"
    assert plan["brand_identity"]["palette"]["accent"] == "#A34B30"
    (example / "brand/fonts/Manrope.ttf").unlink()
    failed = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "story", "--request",
        str(example / "request.json"), "--story", str(example / "feature.json"), "--brand-dir",
        str(example / "brand")], cwd=tmp_path, capture_output=True, text=True)
    assert failed.returncode == 2
    assert "weight files" in failed.stderr


def test_agent_skill_can_be_installed_without_private_tools(tmp_path):
    invoke(tmp_path, "skill", tmp_path / "skills/taskfilm-video")
    skill = (tmp_path / "skills/taskfilm-video/SKILL.md").read_text()
    assert skill.startswith("---\nname: taskfilm-video\n")


def test_doctor_reports_actual_install(tmp_path):
    report = json.loads(invoke(tmp_path, "doctor", "--json").stdout)
    assert report["planning_ready"] is True
    assert report["checks"]["owners"] is True
    assert report["hyperframes_version"] == "0.8.134"


def test_public_entrypoint_license_and_installed_source_hashes(tmp_path):
    import taskfilm
    distribution = metadata.distribution("taskfilm")
    assert distribution.metadata["License-Expression"] == "MIT"
    assert {point.name for point in distribution.entry_points
            if point.group == "console_scripts"} == {"taskfilm"}
    command = Path(sys.executable).parent / ("taskfilm.exe" if os.name == "nt" else "taskfilm")
    result = subprocess.run([str(command), "--version"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout.strip() == taskfilm.__version__
    manifest = json.loads((Path(__file__).parents[1] / "SOURCE-MANIFEST.json").read_text())
    assert manifest["project_license"] == "MIT"
    package = Path(taskfilm.__file__).parent
    for row in manifest["files"]:
        if row["path"].startswith("src/taskfilm/"):
            installed = package / row["path"].removeprefix("src/taskfilm/")
            assert hashlib.sha256(installed.read_bytes()).hexdigest() == row["sha256"], row["path"]
        if row["license"] == "OFL-1.1" or "/references/brag/" in row["path"]:
            assert row["source_sha256"] == row["sha256"]


@pytest.mark.skipif(os.environ.get("TASKFILM_BROWSER_TEST") != "1", reason="opt-in real browser capture")
def test_real_original_browser_task(example, tmp_path):
    # Recording includes final FFmpeg encoding. Shared CPU hosts can finish
    # the real task and retained assertions before that encode exceeds 120s.
    # Keep a bounded integration deadline without changing the task checks.
    capture_timeout = int(os.environ.get("TASKFILM_CAPTURE_TEST_TIMEOUT", "300"))
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(example / "taskboard"), **kwargs)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = json.loads((example / "capture.json").read_text())
    script["url"] = f"http://127.0.0.1:{server.server_port}/"
    # Keep the real interaction/typing sequence; shorten only labelled waits.
    for step in script["steps"]:
        if step["do"] == "wait":
            step["s"] = 0.15
    source = tmp_path / "capture.json"
    source.write_text(json.dumps(script))
    try:
        invoke(tmp_path, "capture", "check")
        invoke(tmp_path, "capture", "rec", source, "--out-dir", tmp_path / "takes",
               "--no-burn-captions", timeout=capture_timeout)
        invalid = {"name": "Rejected result", "url": script["url"], "viewport": script["viewport"],
                   "steps": [{"do": "assert", "selector": "#count", "text": "not the result",
                              "screenshot": "failed.png", "timeout": 0.2}]}
        rejected = tmp_path / "invalid-capture.json"
        rejected.write_text(json.dumps(invalid))
        failure = subprocess.run([sys.executable, "-I", "-m", "taskfilm", "capture", "rec",
            str(rejected), "--out-dir", str(tmp_path / "rejected")], cwd=tmp_path,
            capture_output=True, text=True, timeout=capture_timeout)
        assert failure.returncode != 0
        rejected_manifest = json.loads(next((tmp_path / "rejected").glob("*/session.json")).read_text())
        assert rejected_manifest["steps"]["ok"] == 0
        assert rejected_manifest["assertions"][0]["status"] == "failed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    takes = list((tmp_path / "takes").glob("*/session.json"))
    assert len(takes) == 1
    take = takes[0].parent
    manifest = json.loads(takes[0].read_text())
    assert manifest["steps"]["ok"] == manifest["steps"]["total"]
    assert manifest["streams"]["screen"]["status"] == "ok"
    assert (take / "screen.mp4").stat().st_size > 1000
    assert len(manifest["assertions"]) == 3
    for proof in manifest["assertions"]:
        assert proof["status"] == "passed"
        assert hashlib.sha256((take / proof["screenshot"]).read_bytes()).hexdigest() == proof["sha256"]
        assert proof["visual_verification"] == "not_performed"
    invoke(tmp_path, "edit", take, "--no-retime", "--no-aim")
    assert (take / "plan.json").is_file()
    invoke(tmp_path, "compose", take, "--out", tmp_path / "composition", "--no-title")
    package = json.loads((tmp_path / "composition/package.json").read_text())
    assert "hyperframes@0.8.134" in package["scripts"]["render"]
    assert (tmp_path / "composition/assets/capture-font.ttf").is_file()
    assert (tmp_path / "composition/assets/FONT-LICENSE.txt").is_file()


def test_motion_lab_is_portable_and_complete(example, tmp_path):
    lab = example / "motion-lab"
    for name in ("Manrope.ttf", "Manrope-OFL.txt", "GeistMono.ttf", "GeistMono-OFL.txt"):
        assert (lab / "assets" / name).stat().st_size > 100
    from html.parser import HTMLParser

    class Hosts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []

        def handle_starttag(self, tag, attrs):
            row = dict(attrs)
            if "data-composition-src" in row:
                self.rows.append(row)

    parser = Hosts()
    parser.feed((lab / "index.html").read_text())
    assert len(parser.rows) == 4
    assert [(float(row["data-start"]), float(row["data-duration"])) for row in parser.rows] == [
        (0, 6), (6, 7), (13, 7), (20, 4)]
    for row in parser.rows:
        scene = lab / row["data-composition-src"]
        html = scene.read_text()
        assert f"data-composition-id=\"{row['data-composition-id']}\"" in html
        assert f"window.__timelines['{row['data-composition-id']}']" in html
        assert "<template>" in html
