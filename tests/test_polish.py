"""Source-time contracts and real FFmpeg acceptance for screencast imports."""
from __future__ import annotations

from array import array
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import wave

from PIL import Image
import pytest


OWNER = Path(__file__).resolve().parents[2] / "capture-lane"
if not (OWNER / "polish.py").is_file():
    package = importlib.util.find_spec("taskfilm")
    OWNER = Path(package.origin).parent / "_vendor/video/capture-lane"


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.syspath_prepend(str(OWNER))
    for name in ("hfcomp", "plan", "pixels", "screen_style", "polish"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module_spec = importlib.util.spec_from_file_location("polish_acceptance_owner", OWNER / "polish.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.fixture
def recording(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
        "testsrc2=s=320x180:r=30:d=4", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=4",
        "-filter_threads", "1", "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(source)], check=True, capture_output=True, timeout=30)
    return source


MEDIA = {"width": 320, "height": 180, "duration": 4, "audio": True}
EDIT = {"trim": {"start": .5, "end": 3.5}, "cuts": [{"start": 1.5, "end": 2}],
        "speed": [{"start": 2, "end": 3, "rate": 2}],
        "zooms": [{"start": 2.2, "end": 2.8, "x": .7, "y": .4, "ease": "smooth"}],
        "annotations": [{"start": 1.6, "end": 1.9, "text": "Removed"},
                        {"start": 2.1, "end": 3.4, "text": "</script><b>&", "x": .5, "y": .8}],
        "cursor_overlay": True, "cursor": [
            {"t": .8, "x": .2, "y": .3, "click": True},
            {"t": 1.7, "x": .3, "y": .4, "click": True},
            {"t": 2.3, "x": .7, "y": .4, "click": True},
            {"t": 3.2, "x": .5, "y": .6}]}


def test_edits_keep_source_clock_and_remove_cut_events(owner):
    spec = owner.validate(EDIT, MEDIA)
    segments, plan, presentation = owner.compile_edit(spec, MEDIA)
    assert segments == [(.5, 1.5, 1), (2, 3, 2), (3, 3.5, 1)]
    assert plan["duration_s"] == 2
    assert (plan["zooms"][0]["start"], plan["zooms"][0]["end"]) == (1.1, 1.4)
    assert len(presentation["annotations"]) == 1
    assert presentation["annotations"][0]["start"] == 1.05
    assert [c["t"] for c in presentation["clicks"]] == pytest.approx([.3, 1.15])
    assert len(presentation["cursor_segments"]) == 3
    # The new section begins at its current recorded pointer position, rather
    # than tweening through mouse activity removed by the cut.
    assert presentation["cursor_segments"][1]["samples"][0]["t"] == 1
    assert presentation["cursor_segments"][1]["samples"][0]["x"] == .3


@pytest.mark.parametrize("spec,error", [
    ([], "object"), ({"schema": "other/v1"}, "schema"), ({"zooms_typo": []}, "unknown"),
    ({"width": 641}, "even"), ({"width": True}, "finite"), ({"height": 0}, "between"),
    ({"preset": []}, "preset"), ({"style": {"background": "red;display:none"}}, "RRGGBB"),
    ({"style": {"padding": 5000}}, "padding"), ({"style": {"shadow": 1}}, "shadow"),
    ({"trim": {"start": 2, "end": 1}}, "last"), ({"trim": {}}, "requires"),
    ({"speed": [{"start": 0, "end": 1, "rate": 0}]}, "rate"),
    ({"speed": [{"start": 0, "end": 1, "rate": float("nan")}]}, "finite"),
    ({"cuts": [{"start": 0, "end": 2}, {"start": 1, "end": 3}]}, "overlap"),
    ({"zooms": [{"start": 0, "end": 1, "x": -1}]}, "between"),
    ({"zooms": [{"start": 0, "end": 1, "ease": []}]}, "ease"),
    ({"annotations": [{"start": 0, "end": 1, "text": ""}]}, "text"),
    ({"cursor": [{"t": 1, "x": .5, "y": .5}, {"t": 1, "x": .5, "y": .5}]}, "increasing"),
    ({"cursor_overlay": "true"}, "true or false"), ({"auto_zoom": 1}, "true or false"),
    ({"audio": []}, "keep or mute"),
])
def test_bad_specs_are_refused_with_actionable_errors(owner, spec, error):
    with pytest.raises(ValueError, match=error):
        owner.validate(spec, MEDIA)


def test_removing_all_footage_is_refused(owner):
    spec = owner.validate({"cuts": [{"start": 0, "end": 4}]}, MEDIA)
    with pytest.raises(ValueError, match="entire recording"):
        owner.compile_edit(spec, MEDIA)


def test_manual_focus_wins_over_automatic_zoom(owner):
    manual = {"start": .5, "end": 3, "x": .7, "y": .4, "scale": 1.4}
    spec = owner.validate({"auto_zoom": True, "zooms": [manual],
                           "cursor": [{"t": 1.5, "x": .2, "y": .3, "click": True}]}, MEDIA)
    _, plan, _ = owner.compile_edit(spec, MEDIA)
    assert len(plan["zooms"]) == 1 and plan["zooms"][0]["x"] == .7
    spec["zooms"] = []
    _, plan, _ = owner.compile_edit(spec, MEDIA)
    assert len(plan["zooms"]) == 1 and plan["zooms"][0]["x"] == .2


def test_smoothing_reduces_jitter_but_clicks_keep_exact_position(owner):
    cursor = [{"t": 0, "x": .1, "y": .2}, {"t": .01, "x": .9, "y": .8},
              {"t": .02, "x": .7, "y": .5, "click": True}]
    spec = owner.validate({"cursor": cursor, "cursor_smoothing": .1}, MEDIA)
    _, _, presentation = owner.compile_edit(spec, MEDIA)
    samples = presentation["cursor_segments"][0]["samples"]
    assert .1 < samples[1]["x"] < .3
    assert samples[2]["x"] == .7 and samples[2]["y"] == .5


def test_import_retain_audio_edits_source_and_reproduce_saved_spec(owner, recording, tmp_path):
    source_hash = owner.sha256(recording)
    project = tmp_path / "film"
    result = owner.create(recording, project, EDIT, preset="paper", width=640, height=360)
    assert result["duration"] == 2 and result["audio_retained"] is True
    assert result["annotations"] == 1 and result["clicks"] == 2
    assert owner.sha256(project / "original/recording.mp4") == source_hash == owner.sha256(recording)
    edited = owner.probe(project / "assets/screen.mp4")
    assert edited["duration"] == pytest.approx(2, abs=.034) and edited["audio"] is True
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(project / "assets/screen.mp4"),
                    "-f", "null", "-"], check=True, capture_output=True, timeout=30)
    html = (project / "index.html").read_text()
    assert "&lt;/script&gt;&lt;b&gt;&amp;" in html and "Removed" not in html
    assert 'id="polish-cursor"' in html and 'id="vo-source-audio"' in html
    assert "object-fit: contain" in html and 'ease: "sine.inOut"' in html
    report = json.loads((project / "POLISH.json").read_text())
    assert report["evidence"]["final_video_review"] == "not_performed"
    saved = json.loads((project / "edits.json").read_text())
    spec = owner.validate(saved, MEDIA)
    assert spec == saved
    second = owner.create(project / "original/recording.mp4", tmp_path / "revision", saved)
    assert second["segments"] == result["segments"] and second["source"] == result["source"]


@pytest.mark.parametrize("rate", [.5, 2, 8])
def test_slow_and_fast_audio_keep_pitch_and_duration(owner, recording, tmp_path, rate):
    spec = {"trim": {"start": 1, "end": 3}, "speed": [{"start": 1, "end": 3, "rate": rate}]}
    project = tmp_path / "retimed"
    report = owner.create(recording, project, spec, width=640, height=360)
    assert report["duration"] == pytest.approx(2/rate, abs=.001)
    with wave.open(str(project / "assets/source-audio.wav"), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        sr = audio.getframerate()
        assert audio.getnframes()/sr == pytest.approx(2/rate, abs=.05)
        audio.setpos(int(.05*sr))
        samples = array("h", audio.readframes(min(int(.1*sr), audio.getnframes()-int(.05*sr))))
    crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
    frequency = crossings / (len(samples)/sr)
    assert frequency == pytest.approx(660, abs=30)


def test_deliberate_mute_and_default_no_cursor(owner, recording, tmp_path):
    project = tmp_path / "silent"
    report = owner.create(recording, project, {"audio": "mute"}, width=640, height=360)
    assert report["audio_retained"] is False
    assert not (project / "assets/source-audio.wav").exists()
    assert not owner.probe(project / "assets/screen.mp4")["audio"]
    assert 'id="polish-cursor"' not in (project / "index.html").read_text()


def test_existing_project_and_invalid_edit_never_replace_files(owner, recording, tmp_path):
    destination = tmp_path / "already-here"
    destination.mkdir()
    marker = destination / "mine.txt"
    marker.write_text("Keep me")
    with pytest.raises(ValueError, match="new directory"):
        owner.create(recording, destination, {})
    assert marker.read_text() == "Keep me"
    invalid = tmp_path / "invalid"
    with pytest.raises(ValueError, match="entire recording"):
        owner.create(recording, invalid, {"cuts": [{"start": 0, "end": 4}]})
    assert not invalid.exists()


def test_gif_excerpt_decodes_loops_and_refuses_existing_output(owner, recording, tmp_path):
    module_spec = importlib.util.spec_from_file_location("gif_acceptance_owner", OWNER / "gif.py")
    gif = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(gif)
    target = tmp_path / "preview.gif"
    report = gif.convert(recording, target, width=160, fps=10, start=1, duration=.5)
    assert report["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    with Image.open(target) as image:
        assert image.size == (160, 90) and image.n_frames == 5 and image.info["loop"] == 0
        for i in range(image.n_frames):
            image.seek(i)
            image.convert("RGB").load()
    before = target.read_bytes()
    with pytest.raises(ValueError, match="new file"):
        gif.convert(recording, target)
    assert before == target.read_bytes()


def test_installed_commands_from_unrelated_directory(recording, tmp_path):
    # The monorepo route is deliberately not itself an installed owner closure.
    package = importlib.util.find_spec("taskfilm")
    if package is None or not (Path(package.origin).parent / "_vendor/video/capture-lane/polish.py").is_file():
        pytest.skip("installed distribution acceptance is run from the export")
    project = tmp_path / "cli-film"
    for args in (("polish", recording, project, "--width", "640", "--height", "360"),
                 ("gif", recording, "--output", tmp_path / "cli.gif", "--duration", ".3", "--width", "160")):
        result = subprocess.run([sys.executable, "-I", "-m", "taskfilm", *map(str, args)],
                                cwd=tmp_path, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)
